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
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

import psutil

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
            cmdline = " ".join(proc.info["cmdline"] or [])
            if keyword in cmdline:
                return psutil.Process(proc.info["pid"])
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
        print(f"  {label}: process not found")
        return
    print(
        f"  {label}: RSS={snap['rss']:.1f} MB, "
        f"FDs={snap['fds']}, Threads={snap['threads']}, "
        f"Conns={snap['connections']}, CPU={snap['cpu']:.1f}%, "
        f"Children={snap['children']}"
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
    print(f"Request {request_id}: {status} ({elapsed:.2f}s)")
    if not ok:
        # Show last line of stderr for quick diagnosis
        stderr_line = (result.stderr or "").strip().split("\n")[-1]
        print(f"  stderr: {stderr_line}")
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
            if result["ok"]:
                passed += 1
            else:
                failed += 1
    total_time = time.time() - start
    print(f"\nResult: {passed} passed, {failed} failed in {total_time:.2f}s")
    return passed, failed, total_time


def print_table(header, rows):
    """Print an aligned table given a header list and list-of-lists rows."""
    col_widths = [len(h) for h in header]
    for row in rows:
        for i, val in enumerate(row):
            col_widths[i] = max(col_widths[i], len(str(val)))
    fmt = "  ".join(f"{{:>{w}}}" for w in col_widths)
    print(fmt.format(*header))
    print("-" * (sum(col_widths) + 2 * (len(header) - 1)))
    for row in rows:
        print(fmt.format(*row))


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
            print(
                f"ERROR: No preset for agent '{args.agent}'. "
                f"Please provide --prompt explicitly.\n"
                f"Known presets: {known}"
            )
            sys.exit(1)
        args.prompt = preset["prompt"]

    if args.sly_data is None and not args.no_sly_data:
        if preset is not None and preset["sly_data"] is not None:
            args.sly_data = preset["sly_data"]
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
        print(f"WARNING: Could not read server environment: {exc}")
        return

    api_base = server_env.get("OPENAI_API_BASE")
    if api_base is None:
        print(
            "ERROR: neuro-san server does not have OPENAI_API_BASE set.\n"
            f"  Mock LLM server is running on port {mock_port}.\n"
            "  Restart the server with:\n"
            f"    export OPENAI_API_BASE={expected_url}\n"
            "    python -m neuro_san.service.main_loop.server_main_loop"
        )
        sys.exit(1)

    print(f"  OPENAI_API_BASE={api_base}")
    if mock_port not in api_base:
        print(
            f"ERROR: OPENAI_API_BASE does not reference port {mock_port}.\n"
            f"  Mock LLM server is running on port {mock_port},\n"
            f"  but OPENAI_API_BASE={api_base}\n"
            "  Restart the server with:\n"
            f"    export OPENAI_API_BASE={expected_url}\n"
            "    python -m neuro_san.service.main_loop.server_main_loop"
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
        print(
            "ERROR: neuro-san server process not found.\n"
            "Start it first:\n"
            "  python -m neuro_san.service.main_loop.server_main_loop"
        )
        sys.exit(1)
    print(f"Found neuro-san server (PID {server_proc.pid})")

    if mock_proc is None:
        print(
            "ERROR: mock LLM server process not found.\n"
            "Start it first:\n"
            "  python -m tests.mock_llm_server.mock_llm_server --port 8888"
        )
        sys.exit(1)
    print(f"Found mock LLM server (PID {mock_proc.pid})")

    mock_port = get_mock_server_port(mock_proc)
    check_server_api_base(server_proc, mock_port)

    return server_proc, mock_proc


def build_snapshot_row(round_num, before, after):
    """Build a summary table row from before/after snapshots."""
    rss_delta = after['rss'] - before['rss']
    thread_delta = after['threads'] - before['threads']
    return (
        str(round_num),
        f"{before['rss']:.1f}M",
        f"{after['rss']:.1f}M",
        f"+{rss_delta:.1f}M",
        str(after["fds"]),
        f"{before['threads']} -> {after['threads']}",
        f"+{thread_delta}",
        str(after["connections"]),
        f"{after['cpu']:.1f}%",
        str(after["children"]),
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
        print(f"\n{'=' * 60}")
        print(f"  ROUND {round_num} of {args.num_rounds} "
              f"({args.num_requests} requests, {args.max_workers} workers)")
        print("=" * 60)

        before_server = snapshot(server_proc) if server_proc else None
        before_mock = snapshot(mock_proc) if mock_proc else None
        if before_server:
            print_snapshot("Server BEFORE", before_server)

        print(f"\nFiring {args.num_requests} concurrent requests "
              f"with {args.max_workers} workers...")
        passed, failed, elapsed = run_round(args, cmd)
        totals["passed"] += passed
        totals["failed"] += failed
        totals["time"] += elapsed

        print(f"\nWaiting {args.settle_time}s for server cleanup...")
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
    print(f"\n{label} overall deltas "
          f"(round 1 before vs round {num_rounds} settled):")
    print(f"  RSS:         "
          f"+{float(last[2].rstrip('M')) - float(first[1].rstrip('M')):.1f} MB")
    print(f"  FDs:         "
          f"+{int(last[4]) - int(first[4])}")
    print(f"  Threads:     "
          f"+{int(last[5].split(' -> ')[1]) - int(first[5].split(' -> ')[0])}")
    print(f"  Connections: "
          f"+{int(last[7]) - int(first[7])}")
    print(f"  Children:    "
          f"+{int(last[9]) - int(first[9])}")


def print_results(args, totals, server_rows, mock_rows):
    """Print the overall results summary and leak analysis tables."""
    total_requests = args.num_requests * args.num_rounds

    print(f"\n{'=' * 60}")
    print("  OVERALL RESULTS")
    print("=" * 60)
    print(f"  Total requests: {total_requests} "
          f"({totals['passed']} passed, {totals['failed']} failed)")
    print(f"  Total time:     {totals['time']:.2f}s")
    if total_requests > 0:
        print(f"  Avg per request: {totals['time'] / total_requests:.2f}s")

    header = ["Round", "Before RSS", "Settled RSS", "RSS Delta",
              "FDs", "Threads", "Thread Delta",
              "Conns", "CPU%", "Children"]

    print(f"\n{'=' * 60}")
    print(f"  LEAK ANALYSIS ACROSS {args.num_rounds} ROUNDS "
          f"({total_requests} total requests)")
    print("=" * 60)

    if server_rows:
        print("\nNEURO-SAN SERVER:")
        print_table(header, server_rows)

    if mock_rows:
        print("\nMOCK LLM SERVER:")
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
        print(f"Remote mode: targeting {args.host}:{args.port}")
        print("  Process monitoring disabled (server is not local)")

    print(f"\nConfig: agent={args.agent}, requests={args.num_requests}, "
          f"workers={args.max_workers}, rounds={args.num_rounds}, "
          f"host={args.host}, port={args.port}")
    if not args.no_sly_data:
        print(f"  sly_data={args.sly_data}")
    print(f"  prompt=\"{args.prompt}\"")
    print(f"  settle_time={args.settle_time}s")

    server_rows, mock_rows, totals = run_rounds(
        args, cmd, server_proc, mock_proc)

    print_results(args, totals, server_rows, mock_rows)


if __name__ == "__main__":
    main()
