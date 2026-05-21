import subprocess
import time
import platform
import psutil
from concurrent.futures import ThreadPoolExecutor


def find_process(keyword):
    """Find a process by keyword in its command line."""
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmdline = " ".join(proc.info["cmdline"] or [])
            if keyword in cmdline:
                return psutil.Process(proc.info["pid"])
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return None


def snapshot_process(ps, name):
    """Capture a resource snapshot of a process."""
    if ps is None:
        return None
    try:
        mem = ps.memory_info()
        cpu = ps.cpu_percent(interval=0.5)
        children = ps.children(recursive=True)
        child_count = len(children)
        total_cpu = cpu
        for child in children:
            try:
                total_cpu += child.cpu_percent(interval=0)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return {
            "name": name,
            "rss_mb": mem.rss / (1024 * 1024),
            "vms_mb": mem.vms / (1024 * 1024),
            "num_fds": ps.num_fds() if hasattr(ps, "num_fds") else len(ps.open_files()),
            "num_threads": ps.num_threads(),
            "num_connections": len(ps.net_connections()),
            "cpu_percent": cpu,
            "total_cpu_percent": total_cpu,
            "num_children": child_count,
        }
    except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
        print(f"  Warning: could not snapshot {name}: {e}")
        return None


def print_snapshot(label, snap):
    if snap is None:
        print(f"  {label}: (unavailable)")
        return
    print(f"  {label}: RSS={snap['rss_mb']:.1f} MB, "
          f"FDs={snap['num_fds']}, Threads={snap['num_threads']}, "
          f"Conns={snap['num_connections']}, "
          f"CPU={snap['cpu_percent']:.1f}%, "
          f"TotalCPU={snap['total_cpu_percent']:.1f}%, "
          f"Children={snap['num_children']}")


def run_one(i):
    start = time.time()
    proc = subprocess.Popen(
        [
            "python", "-m", "neuro_san.client.agent_cli",
            "--http", "--agent", "math_guy_mock_llm_service",
            "--first_prompt_file", "/tmp/prompt.txt",
            "--one_shot",
            "--no_thinking_file",
            "--sly_data", '{"x": 3, "y": 5}',
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    ps = psutil.Process(proc.pid)
    peak_rss_mb = 0.0
    while proc.poll() is None:
        try:
            rss_mb = ps.memory_info().rss / (1024 * 1024)
            if rss_mb > peak_rss_mb:
                peak_rss_mb = rss_mb
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        time.sleep(0.1)

    stdout, stderr = proc.communicate()
    elapsed = time.time() - start
    has_error = "exception" in stdout.lower() or "error" in stdout.lower()
    status = "OK" if proc.returncode == 0 and not has_error else "FAIL"
    print(f"  Request {i}: {status} ({elapsed:.2f}s) | Worker Peak RSS: {peak_rss_mb:.1f} MB")
    if has_error:
        print(f"    Response contained error: {stdout[-300:]}")
    if proc.returncode != 0:
        print(f"    stderr: {stderr[-300:]}")
    return proc.returncode, peak_rss_mb, has_error


def run_one_round(round_num, num_requests, max_workers, server_ps, mock_ps):
    print(f"\n{'='*60}")
    print(f"  ROUND {round_num}")
    print(f"{'='*60}")

    snap_server_before = snapshot_process(server_ps, "neuro-san server")
    snap_mock_before = snapshot_process(mock_ps, "mock LLM server")
    print_snapshot("Server Before", snap_server_before)
    print_snapshot("Mock   Before", snap_mock_before)

    print(f"\n  Firing {num_requests} concurrent requests...")
    overall_start = time.time()

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        results = list(pool.map(run_one, range(1, num_requests + 1)))

    overall_elapsed = time.time() - overall_start

    snap_server_after = snapshot_process(server_ps, "neuro-san server")
    snap_mock_after = snapshot_process(mock_ps, "mock LLM server")
    print(f"\n  After load:")
    print_snapshot("Server After", snap_server_after)
    print_snapshot("Mock   After", snap_mock_after)

    print("\n  Waiting 10s for cleanup...")
    time.sleep(10)

    snap_server_settled = snapshot_process(server_ps, "neuro-san server")
    snap_mock_settled = snapshot_process(mock_ps, "mock LLM server")
    print_snapshot("Server Settled", snap_server_settled)
    print_snapshot("Mock   Settled", snap_mock_settled)

    passed = sum(1 for rc, _, err in results if rc == 0 and not err)
    failed = num_requests - passed
    print(f"\n  Result: {passed} passed, {failed} failed in {overall_elapsed:.2f}s")

    return {
        "server_before": snap_server_before,
        "server_settled": snap_server_settled,
        "mock_before": snap_mock_before,
        "mock_settled": snap_mock_settled,
        "passed": passed,
        "failed": failed,
        "elapsed": overall_elapsed,
    }


def print_leak_analysis(rounds, num_rounds, num_requests):
    print(f"\n{'='*60}")
    print(f"  LEAK ANALYSIS ACROSS {num_rounds} ROUNDS ({num_rounds * num_requests} total requests)")
    print(f"{'='*60}")

    print(f"\n  NEURO-SAN SERVER:")
    print(f"  {'Round':<8} {'Before RSS':>12} {'Settled RSS':>12} {'FDs':>6} {'Threads':>9} {'Conns':>7} {'CPU%':>7} {'Children':>10}")
    print(f"  {'-'*72}")
    for i, r in enumerate(rounds, 1):
        s = r["server_settled"]
        b = r["server_before"]
        if s and b:
            print(f"  {i:<8} {b['rss_mb']:>11.1f}M {s['rss_mb']:>11.1f}M "
                  f"{s['num_fds']:>6} {s['num_threads']:>9} {s['num_connections']:>7} "
                  f"{s['total_cpu_percent']:>6.1f}% {s['num_children']:>10}")

    print(f"\n  MOCK LLM SERVER:")
    print(f"  {'Round':<8} {'Before RSS':>12} {'Settled RSS':>12} {'FDs':>6} {'Threads':>9} {'Conns':>7} {'CPU%':>7} {'Children':>10}")
    print(f"  {'-'*72}")
    for i, r in enumerate(rounds, 1):
        s = r["mock_settled"]
        b = r["mock_before"]
        if s and b:
            print(f"  {i:<8} {b['rss_mb']:>11.1f}M {s['rss_mb']:>11.1f}M "
                  f"{s['num_fds']:>6} {s['num_threads']:>9} {s['num_connections']:>7} "
                  f"{s['total_cpu_percent']:>6.1f}% {s['num_children']:>10}")

    if rounds[0]["server_before"] and rounds[-1]["server_settled"]:
        first = rounds[0]["server_before"]
        last = rounds[-1]["server_settled"]
        print(f"\n  Server overall deltas (round 1 before vs round {num_rounds} settled):")
        print(f"    RSS:          {last['rss_mb'] - first['rss_mb']:+.1f} MB")
        print(f"    FDs:          {last['num_fds'] - first['num_fds']:+d}")
        print(f"    Threads:      {last['num_threads'] - first['num_threads']:+d}")
        print(f"    Connections:  {last['num_connections'] - first['num_connections']:+d}")
        print(f"    Children:     {last['num_children'] - first['num_children']:+d}")

    if rounds[0]["mock_before"] and rounds[-1]["mock_settled"]:
        first = rounds[0]["mock_before"]
        last = rounds[-1]["mock_settled"]
        print(f"\n  Mock overall deltas (round 1 before vs round {num_rounds} settled):")
        print(f"    RSS:          {last['rss_mb'] - first['rss_mb']:+.1f} MB")
        print(f"    FDs:          {last['num_fds'] - first['num_fds']:+d}")
        print(f"    Threads:      {last['num_threads'] - first['num_threads']:+d}")
        print(f"    Connections:  {last['num_connections'] - first['num_connections']:+d}")
        print(f"    Children:     {last['num_children'] - first['num_children']:+d}")


if __name__ == "__main__":
    num_rounds = 5
    num_requests = 10
    max_workers = 10

    # System info
    cpu_count_physical = psutil.cpu_count(logical=False)
    cpu_count_logical = psutil.cpu_count(logical=True)
    total_ram = psutil.virtual_memory().total / (1024 * 1024 * 1024)
    available_ram = psutil.virtual_memory().available / (1024 * 1024 * 1024)
    swap_total = psutil.swap_memory().total / (1024 * 1024 * 1024)

    print(f"{'='*60}")
    print(f"  SYSTEM INFO")
    print(f"{'='*60}")
    print(f"  OS:              {platform.system()} {platform.release()}")
    print(f"  CPU:             {platform.processor()}")
    print(f"  Physical cores:  {cpu_count_physical}")
    print(f"  Logical cores:   {cpu_count_logical}")
    print(f"  Total RAM:       {total_ram:.1f} GB")
    print(f"  Available RAM:   {available_ram:.1f} GB")
    print(f"  Swap:            {swap_total:.1f} GB")
    print(f"{'='*60}")
    print(f"  Test config: {num_rounds} rounds x {num_requests} requests, {max_workers} concurrent workers")
    print(f"{'='*60}")

    server_ps = find_process("server_main_loop")
    mock_ps = find_process("mock_llm_server")

    if server_ps:
        print(f"Found neuro-san server (PID {server_ps.pid})")
    else:
        print("WARNING: Could not find neuro-san server process.")

    if mock_ps:
        print(f"Found mock LLM server (PID {mock_ps.pid})")
    else:
        print("WARNING: Could not find mock LLM server process.")

    round_results = []
    for round_num in range(1, num_rounds + 1):
        result = run_one_round(round_num, num_requests, max_workers, server_ps, mock_ps)
        round_results.append(result)

    print_leak_analysis(round_results, num_rounds, num_requests)
