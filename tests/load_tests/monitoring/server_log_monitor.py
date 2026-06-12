"""Server log monitoring — retry counting, request tracking, and disconnection scanning.

Interim implementation. May be replaced by neuro-san built-in
monitoring and telemetry when those features become available.
"""

import logging
import re
import threading
import time
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from tests.load_tests.config import RETRY_LOG_PATTERN
from tests.load_tests.config import REQUEST_START_PATTERN
from tests.load_tests.config import REQUEST_FINISH_PATTERN
from tests.load_tests.config import CLIENT_DISCONNECT_PATTERN
from tests.load_tests.config import STREAM_CLOSED_REQUEST_PATTERN
from tests.load_tests.config import TASK_CANCELLED_PATTERN
from tests.load_tests.monitoring.resource_monitor import snapshot

logger = logging.getLogger(__name__)


def read_log_position(server_log) -> Optional[int]:
    """Return the current end position of the server log file."""
    if server_log is None:
        return None
    try:
        with open(server_log, "r", encoding="utf-8") as log_fh:
            log_fh.seek(0, 2)
            return log_fh.tell()
    except (OSError, IOError):
        return None


def count_retries_since(server_log, position) -> Dict[str, int]:
    """Count max_attempts retry log entries since the given position.

    Returns a dict of error_type -> count for each tracked error type.
    """
    if server_log is None or position is None:
        return {}
    retry_counts: Dict[str, int] = {}
    try:
        with open(server_log, "r", encoding="utf-8") as log_fh:
            log_fh.seek(position)
            for line in log_fh:
                match = RETRY_LOG_PATTERN.search(line)
                if match:
                    error_type = match.group(2)
                    retry_counts[error_type] = retry_counts.get(error_type, 0) + 1
    except (OSError, IOError):
        pass
    return retry_counts


def count_requests_since(server_log, position,
                         primary_start_pattern, primary_finish_pattern):
    """Count request Start/Finish entries since the given position.

    Uses agent-specific patterns for primary requests.
    """
    if server_log is None or position is None:
        return {
            "primary_started": None, "primary_finished": None,
            "total_started": None, "total_finished": None,
        }
    primary_started = 0
    primary_finished = 0
    total_started = 0
    total_finished = 0
    pri_start_re = re.compile(primary_start_pattern)
    pri_finish_re = re.compile(primary_finish_pattern)
    try:
        with open(server_log, "r", encoding="utf-8") as log_fh:
            log_fh.seek(position)
            for line in log_fh:
                if REQUEST_START_PATTERN.search(line):
                    total_started += 1
                if REQUEST_FINISH_PATTERN.search(line):
                    total_finished += 1
                if pri_start_re.search(line):
                    primary_started += 1
                if pri_finish_re.search(line):
                    primary_finished += 1
    except (OSError, IOError):
        pass
    return {
        "primary_started": primary_started,
        "primary_finished": primary_finished,
        "total_started": total_started,
        "total_finished": total_finished,
    }


def parse_token_accounting_since(server_log, position) -> Dict[str, Dict[str, Any]]:
    """Parse Request reporting entries for token accounting data.

    Returns a dict of request_id -> token data, where each entry has:
        total_tokens, prompt_tokens, completion_tokens,
        successful_requests, model
    """
    if server_log is None or position is None:
        return {}
    results: Dict[str, Dict[str, Any]] = {}
    try:
        with open(server_log, "r", encoding="utf-8") as log_fh:
            log_fh.seek(position)
            in_block = False
            block_lines: List[str] = []
            for line in log_fh:
                if "Request reporting" in line and not in_block:
                    in_block = True
                    block_lines = [line]
                elif in_block:
                    block_lines.append(line)
                    if '"request_id"' in line:
                        full_block = "".join(block_lines)
                        entry = _extract_token_entry(full_block)
                        if entry:
                            results[entry["request_id"]] = entry
                        in_block = False
                        block_lines = []
    except (OSError, IOError):
        pass
    return results


def _extract_token_entry(block: str) -> Optional[Dict[str, Any]]:
    """Extract token accounting fields from a Request reporting log block."""
    rid_match = re.search(r'"request_id": "([^"]+)"', block)
    if not rid_match:
        return None
    total = re.search(r'"total_tokens": (\d+)', block)
    prompt = re.search(r'"prompt_tokens": (\d+)', block)
    completion = re.search(r'"completion_tokens": (\d+)', block)
    llm_calls = re.search(r'"successful_requests": (\d+)', block)
    model_names = re.findall(
        r'"(gpt[^"]+|claude[^"]+|gemini[^"]+|o\d[^"]*)"', block,
    )
    return {
        "request_id": rid_match.group(1),
        "total_tokens": int(total.group(1)) if total else 0,
        "prompt_tokens": int(prompt.group(1)) if prompt else 0,
        "completion_tokens": int(completion.group(1)) if completion else 0,
        "llm_calls": int(llm_calls.group(1)) if llm_calls else 0,
        "model": model_names[0] if model_names else "unknown",
    }


def scan_disconnections_since(server_log, position) -> List[Dict[str, Any]]:
    """Scan server log for client disconnections since the given position.

    Returns a list of dicts with request_id and the agent that was
    still running when the client disconnected.
    """
    if server_log is None or position is None:
        return []
    disconnections = {}
    try:
        with open(server_log, "r", encoding="utf-8") as log_fh:
            log_fh.seek(position)
            context_request_id = None
            for line in log_fh:
                req_match = STREAM_CLOSED_REQUEST_PATTERN.search(line)
                if req_match:
                    context_request_id = req_match.group(1)
                if CLIENT_DISCONNECT_PATTERN.search(line):
                    req_id = context_request_id or "unknown"
                    if req_id not in disconnections:
                        disconnections[req_id] = {
                            "request_id": req_id,
                            "agent": "unknown",
                        }
                cancel_match = TASK_CANCELLED_PATTERN.search(line)
                if cancel_match and context_request_id:
                    agent = cancel_match.group(1)
                    if context_request_id in disconnections:
                        disconnections[context_request_id]["agent"] = agent
    except (OSError, IOError):
        pass
    return list(disconnections.values())


def start_log_monitor(server_log, position, expected_count,
                      fire_time, client_proc, primary_start_pattern):
    """Start a background thread to monitor server log for request arrivals.

    Returns (stop_event, thread, peak_result).
    Returns (None, None, None) if monitoring is not available.
    """
    if server_log is None or position is None:
        return None, None, None
    stop_event = threading.Event()
    peak_result = {}
    monitor = threading.Thread(
        target=_log_monitor_worker,
        args=(server_log, position, expected_count, stop_event,
              fire_time, client_proc, peak_result, primary_start_pattern),
        daemon=True,
    )
    monitor.start()
    return stop_event, monitor, peak_result


# pylint: disable=too-many-arguments,too-many-positional-arguments
def _log_monitor_worker(server_log, position, expected_count, stop_event,
                        fire_time, client_proc, peak_result,
                        primary_start_pattern):
    """Background worker that tails server log and reports request arrivals."""
    count = 0
    pri_start_re = re.compile(primary_start_pattern)
    agent_label = primary_start_pattern.split("/")[0].split(" ")[-1]
    try:
        with open(server_log, "r", encoding="utf-8") as log_fh:
            log_fh.seek(position)
            while not stop_event.is_set() and count < expected_count:
                line = log_fh.readline()
                if line:
                    if pri_start_re.search(line):
                        count += 1
                        now = time.time()
                        ts = time.strftime("%H:%M:%S", time.localtime(now))
                        delta = now - fire_time
                        logger.info(
                            "  [server] %s request %s/%s "
                            "received [%s] (+%.1fs)",
                            agent_label, count, expected_count, ts, delta,
                        )
                        if count >= expected_count:
                            snap = snapshot(client_proc)
                            if snap:
                                logger.info(
                                    "  Client AFTER: "
                                    "RSS %.1fM, CPU %.1f%%",
                                    snap["rss"], snap["cpu"],
                                )
                                peak_result.update(snap)
                else:
                    stop_event.wait(0.5)
    except (OSError, IOError):
        pass
