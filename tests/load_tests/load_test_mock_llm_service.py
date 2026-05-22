#!/usr/bin/env python
"""
Load-test script for neuro-san server using the mock LLM service.

Fires concurrent requests via agent_cli subprocesses, monitors the
neuro-san server and mock LLM server processes for resource leaks
(RSS, FDs, threads, connections), and prints a per-round summary
with an overall leak analysis.

Prerequisites:
    1. Mock LLM server running (Terminal 1):
       python -m tests.mock_llm_server.mock_llm_server --port 8888

    2. Neuro-san server running with OPENAI_API_BASE (Terminal 2):
       export OPENAI_API_BASE=http://localhost:8888/v1
       python -m neuro_san.service.main_loop.server_main_loop

Usage examples:
    # Defaults: math_guy with preset prompt/sly-data, 5 rounds, 10 requests, 10 workers
    python tests/load_tests/load_test_mock_llm_service.py

    # 100 concurrent requests over 3 rounds
    python tests/load_tests/load_test_mock_llm_service.py --num-requests 100 --max-workers 100 --num-rounds 3

    # Different agent network (preset auto-fills prompt, no sly-data)
    python tests/load_tests/load_test_mock_llm_service.py --agent hello_world

    # Override preset prompt for a known agent
    python tests/load_tests/load_test_mock_llm_service.py --agent hello_world --prompt "Say hi to the moon"

    # Unknown agent requires explicit --prompt
    python tests/load_tests/load_test_mock_llm_service.py --agent my_custom_agent --prompt "test input" --no-sly-data

    # Remote neuro-san server (psutil monitoring auto-disabled)
    python tests/load_tests/load_test_mock_llm_service.py --host 172.31.11.243 --port 8080
"""

import argparse
import logging
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

import psutil

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}

# Agent-specific presets for prompt and sly-data.
# Add new agents here as they become available for load testing.
AGENT_PRESETS = {
    "math_guy": {
        "prompt": "add",
        "sly_data": '{"x": 3, "y": 5}',
    },
    "hello_world": {
        "prompt": "Greet developers that wrote their very first program",
        "sly_data": None,
    },
    "chat_mock_llm_echo": {
        "prompt": "Hello, testing the mock LLM",
        "sly_data": None,
    },
}


def parse_args():
    """Parse command-line arguments for load test configuration."""
    parser = argparse.ArgumentParser(
        description="Load-test neuro-san server with resource leak detection.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--agent",
        type=str,
        default="math_guy",
        help="Agent network name to test (default: math_guy)",
    )
    parser.add_argument(
        "--num-requests",
        type=int,
        default=10,
        help="Number of requests per round (default: 10)",
    )
    parser.add_argument(
        "--max-workers",
        type=int,
        default=10,
        help="Max concurrent workers (default: 10)",
    )
    parser.add_argument(
        "--num-rounds",
        type=int,
        default=5,
        help="Number of rounds to run (default: 5)",
    )
    parser.add_argument(
        "--prompt",
        type=str,
        default=None,
        help="Prompt text to send to the agent. "
             "Auto-filled from preset if agent is known.",
    )
    parser.add_argument(
        "--sly-data",
        type=str,
        default=None,
        help="JSON sly_data string. Auto-filled from preset if agent is known. "
             "Use --no-sly-data to omit.",
    )
    parser.add_argument(
        "--no-sly-data",
        action="store_true",
        default=False,
        help="Do not pass --sly_data to agent_cli",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="localhost",
        help="Neuro-san server host (default: localhost)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Neuro-san server port (default: 8080)",
    )
    parser.add_argument(
        "--settle-time",
        type=int,
        default=10,
        help="Seconds to wait after each round for cleanup (default: 10)",
    )
    return parser.parse_args()


def find_process(keyword):
    """Find a running process whose command line contains the given keyword."""
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmdline = " ".join(proc.info.get("cmdline") or [])
            if keyword in cmdline:
                return psutil.Process(proc.info.get("pid"))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None


def snapshot(proc) -> Optional[Dict[str, Any]]:
    """Capture a point-in-time resource snapshot of a process."""
    try:
        mem = proc.memory_info()
        return {
            "rss": mem.rss / 1024 / 1024,
            "fds": proc.num_fds(),
            "threads": proc.num_threads(),
            "connections": len(proc.net_connections()),
            "children": len(proc.children()),
            "cpu": proc.cpu_percent(interval=0.1),
        }
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None


def print_snapshot(label, snap):
    """Pretty-print a single resource snapshot."""
    if snap is None:
        logger.info("  %s: process not found", label)
        return
    logger.info(
        "  %s: RSS=%.1f MB, FDs=%s, Threads=%s, Conns=%s, CPU=%.1f%%, Children=%s",
        label, snap.get("rss"), snap.get("fds"), snap.get("threads"),
        snap.get("connections"), snap.get("cpu"), snap.get("children"),
    )


def build_cli_command(args, prompt_file):
    """
    Build the agent_cli subprocess command list from parsed arguments.
    Includes --no_thinking_file to avoid race conditions under concurrency.
    """
    cmd = [
        "python", "-m", "neuro_san.client.agent_cli",
        "--http",
        "--host", args.host,
        "--port", str(args.port),
        "--agent", args.agent,
        "--first_prompt_file", prompt_file,
        "--one_shot",
        "--no_thinking_file",
    ]
    if not args.no_sly_data:
        cmd.extend(["--sly_data", args.sly_data])
    return cmd


def run_one(request_id, cmd):
    """Execute a single agent_cli request and return timing + status."""
    start = time.time()
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    elapsed = time.time() - start
    ok = result.returncode == 0
    status = "OK" if ok else "FAIL"
    logger.info("Request %s: %s (%.2fs)", request_id, status, elapsed)
    if not ok:
        # Show last line of stderr for quick diagnosis
        stderr_line = (result.stderr or "").strip().split("\n")[-1]
        logger.info("  stderr: %s", stderr_line)
    return {"ok": ok, "elapsed": elapsed}


def run_round(args, cmd):
    """Fire num_requests concurrent requests using a thread pool."""
    passed = 0
    failed = 0
    start = time.time()
    with ThreadPoolExecutor(max_workers=args.max_workers) as pool:
        futures = [
            pool.submit(run_one, i + 1, cmd)
            for i in range(args.num_requests)
        ]
        for f in futures:
            result = f.result()
            if result.get("ok"):
                passed += 1
            else:
                failed += 1
    total_time = time.time() - start
    logger.info("\nResult: %s passed, %s failed in %.2fs", passed, failed, total_time)
    return passed, failed, total_time


def print_table(header, rows):
    """Print an aligned table given a header list and list-of-lists rows."""
    col_widths = [len(h) for h in header]
    for row in rows:
        for i, val in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(val)))
    fmt = "  ".join(f"{{:>{w}}}" for w in col_widths)
    logger.info("%s", fmt.format(*header))
    logger.info("%s", "-" * (sum(col_widths) + 2 * (len(header) - 1)))
    for row in rows:
        logger.info("%s", fmt.format(*row))


def apply_presets(args):
    """
    Fill in prompt and sly-data from AGENT_PRESETS when the user has not
    provided them explicitly. Abort if the agent is unknown and --prompt
    is missing.
    """
    preset = AGENT_PRESETS.get(args.agent)

    if args.prompt is None:
        if preset is None:
            known = ", ".join(sorted(AGENT_PRESETS.keys()))
            logger.error(
                "No preset for agent '%s'. "
                "Please provide --prompt explicitly.\n"
                "Known presets: %s",
                args.agent, known,
            )
            sys.exit(1)
        args.prompt = preset.get("prompt")

    if args.sly_data is None and not args.no_sly_data:
        if preset is not None and preset.get("sly_data") is not None:
            args.sly_data = preset.get("sly_data")
        else:
            args.no_sly_data = True


def get_mock_server_port(mock_proc):
    """Extract the --port value from the mock LLM server's command line."""
    try:
        cmdline = mock_proc.cmdline()
        for i, arg in enumerate(cmdline):
            if arg == "--port" and i + 1 < len(cmdline):
                return cmdline[i + 1]
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass
    return "8888"


def check_server_api_base(server_proc, mock_port):
    """
    Verify that the neuro-san server has OPENAI_API_BASE set and
    that it points to the correct mock LLM server port.
    Exits with an error if not set or mismatched.
    """
    expected_url = f"http://localhost:{mock_port}/v1"
    try:
        server_env = server_proc.environ()
    except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
        logger.warning("Could not read server environment: %s", exc)
        return

    api_base = server_env.get("OPENAI_API_BASE")
    if api_base is None:
        logger.error(
            "neuro-san server does not have OPENAI_API_BASE set.\n"
            "  Mock LLM server is running on port %s.\n"
            "  Restart the server with:\n"
            "    export OPENAI_API_BASE=%s\n"
            "    python -m neuro_san.service.main_loop.server_main_loop",
            mock_port, expected_url,
        )
        sys.exit(1)

    logger.info("  OPENAI_API_BASE=%s", api_base)
    if mock_port not in api_base:
        logger.error(
            "OPENAI_API_BASE does not reference port %s.\n"
            "  Mock LLM server is running on port %s,\n"
            "  but OPENAI_API_BASE=%s\n"
            "  Restart the server with:\n"
            "    export OPENAI_API_BASE=%s\n"
            "    python -m neuro_san.service.main_loop.server_main_loop",
            mock_port, mock_port, api_base, expected_url,
        )
        sys.exit(1)


def find_local_processes():
    """
    Locate neuro-san server and mock LLM server processes.
    Exits with an error if either is not found.
    Also validates the server's OPENAI_API_BASE matches the mock port.
    """
    server_proc = find_process("server_main_loop")
    mock_proc = find_process("mock_llm_server")

    if server_proc is None:
        logger.error(
            "neuro-san server process not found.\n"
            "Start it first:\n"
            "  python -m neuro_san.service.main_loop.server_main_loop"
        )
        sys.exit(1)
    logger.info("Found neuro-san server (PID %s)", server_proc.pid)

    if mock_proc is None:
        logger.error(
            "mock LLM server process not found.\n"
            "Start it first:\n"
            "  python -m tests.mock_llm_server.mock_llm_server --port 8888"
        )
        sys.exit(1)
    logger.info("Found mock LLM server (PID %s)", mock_proc.pid)

    mock_port = get_mock_server_port(mock_proc)
    check_server_api_base(server_proc, mock_port)

    return server_proc, mock_proc


def build_snapshot_row(round_num, before, after):
    """Build a summary table row from before/after snapshots."""
    rss_delta = after.get("rss") - before.get("rss")
    thread_delta = after.get("threads") - before.get("threads")
    return (
        str(round_num),
        f"{before.get('rss'):.1f}M",
        f"{after.get('rss'):.1f}M",
        f"+{rss_delta:.1f}M",
        str(after.get("fds")),
        f"{before.get('threads')} -> {after.get('threads')}",
        f"+{thread_delta}",
        str(after.get("connections")),
        f"{after.get('cpu'):.1f}%",
        str(after.get("children")),
    )


# pylint: disable=too-many-locals
def run_rounds(args, cmd, server_proc, mock_proc):
    """
    Execute all rounds of the load test, collecting snapshots
    and results per round.
    """
    server_rows: List[Tuple] = []
    mock_rows: List[Tuple] = []
    totals = {"passed": 0, "failed": 0, "time": 0.0}

    for round_num in range(1, args.num_rounds + 1):
        logger.info("\n%s", "=" * 60)
        logger.info(
            "  ROUND %s of %s (%s requests, %s workers)",
            round_num, args.num_rounds, args.num_requests, args.max_workers,
        )
        logger.info("=" * 60)

        before_server = snapshot(server_proc) if server_proc else None
        before_mock = snapshot(mock_proc) if mock_proc else None
        if before_server:
            print_snapshot("Server BEFORE", before_server)

        logger.info(
            "\nFiring %s concurrent requests with %s workers...",
            args.num_requests, args.max_workers,
        )
        passed, failed, elapsed = run_round(args, cmd)
        totals["passed"] = totals.get("passed", 0) + passed
        totals["failed"] = totals.get("failed", 0) + failed
        totals["time"] = totals.get("time", 0.0) + elapsed

        logger.info("\nWaiting %ss for server cleanup...", args.settle_time)
        time.sleep(args.settle_time)

        after_server = snapshot(server_proc) if server_proc else None
        after_mock = snapshot(mock_proc) if mock_proc else None
        if after_server:
            print_snapshot("Server SETTLED", after_server)

        if before_server and after_server:
            server_rows.append(
                build_snapshot_row(round_num, before_server, after_server))
        if before_mock and after_mock:
            mock_rows.append(
                build_snapshot_row(round_num, before_mock, after_mock))

    return server_rows, mock_rows, totals


def print_overall_deltas(label, rows, num_rounds):
    """Print overall resource deltas between the first and last rounds."""
    first = rows[0]
    last = rows[-1]
    logger.info(
        "\n%s overall deltas (round 1 before vs round %s settled):",
        label, num_rounds,
    )
    logger.info(
        "  RSS:         +%.1f MB",
        float(last[2].rstrip("M")) - float(first[1].rstrip("M")),
    )
    logger.info(
        "  FDs:         +%s",
        int(last[4]) - int(first[4]),
    )
    logger.info(
        "  Threads:     +%s",
        int(last[5].split(" -> ")[1]) - int(first[5].split(" -> ")[0]),
    )
    logger.info(
        "  Connections: +%s",
        int(last[7]) - int(first[7]),
    )
    logger.info(
        "  Children:    +%s",
        int(last[9]) - int(first[9]),
    )


def print_results(args, totals, server_rows, mock_rows):
    """Print the overall results summary and leak analysis tables."""
    total_requests = args.num_requests * args.num_rounds

    logger.info("\n%s", "=" * 60)
    logger.info("  OVERALL RESULTS")
    logger.info("=" * 60)
    logger.info(
        "  Total requests: %s (%s passed, %s failed)",
        total_requests, totals.get("passed"), totals.get("failed"),
    )
    logger.info("  Total time:     %.2fs", totals.get("time"))
    if total_requests > 0:
        logger.info(
            "  Avg per request: %.2fs", totals.get("time") / total_requests,
        )

    header = ["Round", "Before RSS", "Settled RSS", "RSS Delta",
              "FDs", "Threads", "Thread Delta",
              "Conns", "CPU%", "Children"]

    logger.info("\n%s", "=" * 60)
    logger.info(
        "  LEAK ANALYSIS ACROSS %s ROUNDS (%s total requests)",
        args.num_rounds, total_requests,
    )
    logger.info("=" * 60)

    if server_rows:
        logger.info("\nNEURO-SAN SERVER:")
        print_table(header, server_rows)

    if mock_rows:
        logger.info("\nMOCK LLM SERVER:")
        print_table(header, mock_rows)

    if len(server_rows) >= 2:
        print_overall_deltas("Server", server_rows, args.num_rounds)

    if len(mock_rows) >= 2:
        print_overall_deltas("Mock", mock_rows, args.num_rounds)


def main():
    """Entry point for the load test script."""
    args = parse_args()
    apply_presets(args)

    prompt_file = "/tmp/load_test_prompt.txt"
    with open(prompt_file, "w", encoding="utf-8") as prompt_fh:
        prompt_fh.write(args.prompt)

    cmd = build_cli_command(args, prompt_file)

    is_local = args.host in LOCAL_HOSTS
    server_proc = None
    mock_proc = None

    if is_local:
        server_proc, mock_proc = find_local_processes()
    else:
        logger.info("Remote mode: targeting %s:%s", args.host, args.port)
        logger.info("  Process monitoring disabled (server is not local)")

    logger.info(
        "\nConfig: agent=%s, requests=%s, workers=%s, rounds=%s, host=%s, port=%s",
        args.agent, args.num_requests, args.max_workers,
        args.num_rounds, args.host, args.port,
    )
    if not args.no_sly_data:
        logger.info("  sly_data=%s", args.sly_data)
    logger.info("  prompt=\"%s\"", args.prompt)
    logger.info("  settle_time=%ss", args.settle_time)

    server_rows, mock_rows, totals = run_rounds(
        args, cmd, server_proc, mock_proc)

    print_results(args, totals, server_rows, mock_rows)


if __name__ == "__main__":
    main()
