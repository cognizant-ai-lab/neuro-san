"""Traffic runner — fires concurrent requests via a thread pool."""

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from typing import Dict
from typing import List

from tests.load_tests.config import STATUS_CREATED
from tests.load_tests.config import STATUS_FAILED
from tests.load_tests.config import STATUS_KILLED
from tests.load_tests.config import STATUS_TIMEOUT
from tests.load_tests.traffic.cli_builder import build_cli_command
from tests.load_tests.traffic.cli_builder import cleanup_prompt_file
from tests.load_tests.traffic.cli_builder import last_stderr_line
from tests.load_tests.traffic.cli_builder import parse_stdout_field
from tests.load_tests.traffic.cli_builder import write_prompt_file
from tests.load_tests.traffic.process_monitor import execute_with_idle_detection

logger = logging.getLogger(__name__)


def run_one(args, profile, request_id, global_request_id,
            output_dir=None, debug=False):
    """Execute a single request with idle-timeout detection.

    Returns a result dict with status, elapsed, prompt, and parsed output fields.
    """
    prompt = profile.get_prompt(global_request_id, same_prompt=args.same_prompt)
    prompt_file = write_prompt_file(global_request_id, prompt)

    cmd = build_cli_command(args.host, args.port, args.agent, prompt_file)
    start = time.time()
    status, stdout, stderr, returncode = execute_with_idle_detection(
        cmd, args.timeout, args.idle_timeout,
    )
    elapsed = time.time() - start

    # Parse output fields defined by the profile
    parsed_fields: Dict[str, str] = {}
    for field in profile.success_fields:
        parsed_fields[field] = parse_stdout_field(stdout, field)

    _save_debug_output(output_dir, debug, request_id, stdout, stderr)

    failure_reason = None
    if status not in (STATUS_TIMEOUT, STATUS_KILLED):
        if profile.success_fields:
            skip_reservation = getattr(args, "skip_reservation_check", False)
            if skip_reservation:
                required = [
                    f for f in profile.success_fields
                    if f != "reservation_id"
                ]
            else:
                required = profile.success_fields
            passed = returncode == 0 and all(
                parsed_fields.get(f) for f in required
            )
        else:
            passed = returncode == 0
        # Non-empty response check: catch pipe buffering or silent failures
        if passed and not stdout.strip():
            passed = False
            failure_reason = "empty response from agent"
        status = STATUS_CREATED if passed else STATUS_FAILED
        if status == STATUS_FAILED and not failure_reason:
            failure_reason = _diagnose_failure(
                returncode, parsed_fields, profile.success_fields,
                getattr(args, "skip_reservation_check", False),
            )

    _log_request_result(request_id, status, elapsed, parsed_fields, failure_reason,
                        stderr, getattr(args, "skip_reservation_check", False))
    cleanup_prompt_file(prompt_file)
    error_line = last_stderr_line(stderr) if status != STATUS_CREATED else None

    result = {
        "request_id": f"request-{request_id}",
        "status": status,
        "elapsed": elapsed,
        "prompt": prompt,
        "error": error_line,
    }
    result.update(parsed_fields)
    return result


def run_stage(args, profile, num_requests, max_workers, global_offset,
              server_proc=None, output_dir=None, debug=False):
    """Fire num_requests concurrent requests using a thread pool."""
    from tests.load_tests.monitoring.heartbeat import progress_heartbeat

    results_list: List[Dict[str, Any]] = []
    peak_threads_result: Dict[str, int] = {}
    start = time.time()
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [
            pool.submit(
                run_one, args, profile,
                i + 1, global_offset + i,
                output_dir, debug,
            )
            for i in range(num_requests)
        ]
        heartbeat_stop = threading.Event()
        heartbeat = threading.Thread(
            target=progress_heartbeat,
            args=(futures, num_requests, start,
                  heartbeat_stop, server_proc,
                  peak_threads_result),
            daemon=True,
        )
        heartbeat.start()
        for future in futures:
            results_list.append(future.result())
        heartbeat_stop.set()
        heartbeat.join(timeout=2)
    total_time = time.time() - start
    return total_time, results_list, peak_threads_result


def count_results(results) -> Dict[str, int]:
    """Count results by status type."""
    counts = {
        STATUS_CREATED: 0,
        STATUS_FAILED: 0,
        STATUS_TIMEOUT: 0,
        STATUS_KILLED: 0,
    }
    for result in results:
        status = result.get("status", STATUS_FAILED)
        counts[status] = counts.get(status, 0) + 1
    return counts


def _diagnose_failure(returncode, parsed_fields, success_fields,
                      skip_reservation_check):
    """Return a human-readable reason why a request was marked FAILED."""
    reasons = []
    if returncode != 0:
        reasons.append(f"non-zero exit code ({returncode})")
    for field in success_fields:
        if field == "reservation_id" and skip_reservation_check:
            continue
        if not parsed_fields.get(field):
            reasons.append(f"missing {field}")
    return "; ".join(reasons) if reasons else "unknown"


def _log_request_result(request_id, status, elapsed, parsed_fields,
                        failure_reason, stderr, skip_reservation_check):
    """Log the result of a single request."""
    logger.info("Request %s: %s (%.2fs)", request_id, status, elapsed)
    for field, value in parsed_fields.items():
        if field == "reservation_id" and skip_reservation_check:
            logger.info("  %s: skipped", field)
        else:
            logger.info("  %s: %s", field, value or "")
    if failure_reason:
        logger.info("  reason: %s", failure_reason)
    if status in (STATUS_FAILED, STATUS_TIMEOUT, STATUS_KILLED):
        logger.info("  stderr: %s", last_stderr_line(stderr))


def log_token_summary(results):
    """Log token usage for each request after token data is attached."""
    has_tokens = any(r.get("total_tokens") for r in results)
    if not has_tokens:
        return
    for result in results:
        total = result.get("total_tokens", 0)
        if not total:
            continue
        prompt_tok = result.get("prompt_tokens", 0)
        comp_tok = result.get("completion_tokens", 0)
        llm_calls = result.get("llm_calls", 0)
        model = result.get("model", "unknown")
        rid = result.get("request_id", "?")
        logger.info(
            "  %s: %s tokens (%s prompt + %s completion), "
            "%s LLM call(s), model=%s",
            rid, f"{total:,}", f"{prompt_tok:,}", f"{comp_tok:,}",
            llm_calls, model,
        )


_debug_dir = None


def _save_debug_output(output_dir, debug, request_id, stdout, stderr):
    """Save raw CLI output to debug directory when debug is enabled."""
    global _debug_dir  # pylint: disable=global-statement
    if not debug:
        return
    if _debug_dir is None:
        _debug_dir = os.path.join(output_dir, "debug")
        os.makedirs(_debug_dir, exist_ok=True)
        logger.info("Debug output directory: %s", _debug_dir)
    stdout_path = os.path.join(_debug_dir, f"request_{request_id}_stdout.txt")
    stderr_path = os.path.join(_debug_dir, f"request_{request_id}_stderr.txt")
    with open(stdout_path, "w", encoding="utf-8") as fh:
        fh.write(stdout)
    if stderr and stderr.strip():
        with open(stderr_path, "w", encoding="utf-8") as fh:
            fh.write(stderr)
