# Copyright © 2023-2026 Cognizant Technology Solutions Corp, www.cognizant.com.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# END COPYRIGHT

"""Server log monitoring — retry counting, request tracking, and disconnection scanning.

Interim implementation. May be replaced by neuro-san built-in
monitoring and telemetry when those features become available.
"""

import json
import logging
import os
import re
import sys
import threading
import time

from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import TextIO
from typing import Tuple
from typing import Union

import psutil

from tests.load_tests.config import CLIENT_DISCONNECT_PATTERN
from tests.load_tests.config import DONE_STREAMING_PATTERN
from tests.load_tests.config import NETWORK_LOOKAHEAD_LINES
from tests.load_tests.config import PROVIDER_RETRY_PATTERN
from tests.load_tests.config import REQUEST_FINISH_PATTERN
from tests.load_tests.config import REQUEST_START_PATTERN
from tests.load_tests.config import RETRY_LOG_PATTERN
from tests.load_tests.config import SERVER_ERROR_PATTERN
from tests.load_tests.config import STREAM_CLOSED_REQUEST_PATTERN
from tests.load_tests.config import TASK_CANCELLED_PATTERN
from tests.load_tests.config import VALIDATION_ATTEMPT_PATTERN
from tests.load_tests.config import VALIDATION_ERROR_PATTERN
from tests.load_tests.config import VALIDATION_REINVOKE_PATTERN
from tests.load_tests.config import VALIDATION_REQUEST_ID_PATTERN
from tests.load_tests.monitoring.resource_monitor import ResourceMonitor
from tests.load_tests.shared_ref import SharedRef

logger = logging.getLogger(__name__)

# Console progress ticks for arrivals: single-line dots written via
# logging (not print()).  An empty terminator keeps the dots on one
# line, and propagate=False stops the root logger from prefixing each
# dot with a timestamp or duplicating it.
_progress_logger = logging.getLogger(__name__ + ".progress")
_progress_logger.propagate = False
if not _progress_logger.handlers:
    _progress_handler = logging.StreamHandler(sys.stdout)
    _progress_handler.terminator = ""
    _progress_handler.setFormatter(logging.Formatter("%(message)s"))
    _progress_logger.addHandler(_progress_handler)
    _progress_logger.setLevel(logging.INFO)


class _NullFile:
    """No-op context manager used when no receipt file is needed."""

    def __enter__(self):
        return None

    def __exit__(self, *args):
        pass


class ServerLogMonitor:
    """Parses a neuro-san server log for retries, tokens, and disconnections.

    Holds the server log path so that callers do not need to pass it
    to every method.
    """

    def __init__(self, server_log: Optional[str]) -> None:
        self._server_log = server_log

    def read_position(self) -> Optional[int]:
        """Return the current end position of the server log file."""
        if self._server_log is None:
            return None
        try:
            with open(self._server_log, "r", encoding="utf-8") as log_fh:
                log_fh.seek(0, 2)
                return log_fh.tell()
        except OSError:
            return None

    def _read_lines_since(self, position, label) -> List[str]:
        """Read all lines from server_log starting at the given position.

        Returns an empty list on read failure.  The label is used in
        the log message when an OSError occurs.
        """
        try:
            with open(self._server_log, "r", encoding="utf-8") as log_fh:
                log_fh.seek(position)
                return log_fh.readlines()
        except OSError as exc:
            logger.info("Could not read server log for %s: %s", label, exc)
            return []

    def count_retries_since(self, position) -> Dict[str, int]:
        """Count retry log entries since the given position.

        Covers both neuro-san's own max_attempts retries ("retrying
        from <ErrorType>") and retries the LLM provider SDK performs
        internally ("Retrying request to ... in ... seconds"), counted
        under the "ProviderRetry" key.  The latter are invisible to
        neuro-san but are still extra LLM attempts, so they belong in
        the amplification factor.

        Returns a dict of error_type -> count for each tracked type.
        """
        if self._server_log is None or position is None:
            return {}
        lines: List[str] = self._read_lines_since(position, "retries")
        retry_counts: Dict[str, int] = {}
        for line in lines:
            match: Optional[re.Match] = RETRY_LOG_PATTERN.search(line)
            if match:
                error_type: str = match.group(2)
                retry_counts[error_type] = retry_counts.get(error_type, 0) + 1
            elif PROVIDER_RETRY_PATTERN.search(line):
                retry_counts["ProviderRetry"] = retry_counts.get("ProviderRetry", 0) + 1
        return retry_counts

    def scan_server_errors_since(self, position) -> List[Dict[str, str]]:
        """Scan for server "Errors detected:" events since position.

        These are logged as JSON with a "message" value that starts
        with "Errors detected:" and spans literal newlines, so the log
        window is joined and matched with a DOTALL pattern.  Returns a
        list of {request_id, message} dicts with the message flattened
        to a single line.
        """
        if self._server_log is None or position is None:
            return []
        lines: List[str] = self._read_lines_since(position, "errors")
        if not lines:
            return []
        text: str = "".join(lines)
        errors: List[Dict[str, str]] = []
        for match in SERVER_ERROR_PATTERN.finditer(text):
            message: str = " ".join(match.group(1).split())
            errors.append({"request_id": match.group(2), "message": message})
        return errors

    def scan_tool_warnings_since(self, position) -> List[Dict[str, str]]:
        """Scan for "Failed to create Agent/tool" warnings since position.

        These are logged as one-line JSON with message_type "Warning"
        and mean a requested tool (e.g. web_search) was unavailable to
        an agent.  They do not affect the created network, but a high
        count under load may point to tool-creation failures.  Returns
        a list of {request_id, message} dicts.
        """
        if self._server_log is None or position is None:
            return []
        lines: List[str] = self._read_lines_since(position, "tool warnings")
        warnings: List[Dict[str, str]] = []
        for line in lines:
            stripped: str = line.strip()
            if "Failed to create Agent/tool" not in stripped:
                continue
            entry: Any = None
            try:
                entry = json.loads(stripped)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(entry, dict):
                continue
            message: str = entry.get("message", "")
            if not message.startswith("Failed to create Agent/tool"):
                continue
            warnings.append({"request_id": entry.get("request_id", "unknown"), "message": " ".join(message.split())})
        return warnings

    def count_requests_since(self, position, primary_start_pattern, primary_finish_pattern) -> Dict[str, Optional[int]]:
        """Count request Start/Finish entries since the given position.

        Uses agent-specific patterns for primary requests.
        """
        none_result: Dict[str, Optional[int]] = {"primary_started": None, "primary_finished": None,
                                                 "total_started": None, "total_finished": None}
        if self._server_log is None or position is None:
            return none_result
        lines: List[str] = self._read_lines_since(position, "counts")
        if not lines:
            return none_result
        primary_started: int = 0
        primary_finished: int = 0
        total_started: int = 0
        total_finished: int = 0
        primary_start_re: re.Pattern = re.compile(primary_start_pattern)
        primary_finish_re: re.Pattern = re.compile(primary_finish_pattern)
        for line in lines:
            if REQUEST_START_PATTERN.search(line):
                total_started += 1
            if REQUEST_FINISH_PATTERN.search(line):
                total_finished += 1
            if primary_start_re.search(line):
                primary_started += 1
            if primary_finish_re.search(line):
                primary_finished += 1
        return {
            "primary_started": primary_started,
            "primary_finished": primary_finished,
            "total_started": total_started,
            "total_finished": total_finished,
        }

    def parse_token_accounting_since(self, position) -> Dict[str, Dict[str, Any]]:
        """Parse Request reporting entries for token accounting data.

        Returns a dict of request_id -> token data, where each entry has:
            total_tokens, prompt_tokens, completion_tokens,
            successful_requests, model, reporting_agent
        """
        if self._server_log is None or position is None:
            return {}
        lines: List[str] = self._read_lines_since(position, "tokens")
        if not lines:
            return {}
        results: Dict[str, Dict[str, Any]] = {}
        for block in self._collect_reporting_blocks(lines):
            entry: Optional[Dict[str, Any]] = self._extract_token_entry(block.get("text", ""))
            if entry:
                request_id: Optional[str] = entry.get("request_id")
                if request_id is not None:
                    agent: Optional[str] = self._find_network_after(lines, block.get("end_idx", 0))
                    if agent:
                        entry["reporting_agent"] = agent
                    results[request_id] = entry
        return results

    @staticmethod
    def _extract_token_entry(block: str) -> Optional[Dict[str, Any]]:
        """Extract token accounting fields from a Request reporting log block."""
        request_id_match: Optional[re.Match] = re.search(r'"request_id": "([^"]+)"', block)
        if not request_id_match:
            return None
        total_match: Optional[re.Match] = re.search(r'"total_tokens": (\d+)', block)
        prompt_match: Optional[re.Match] = re.search(r'"prompt_tokens": (\d+)', block)
        completion_match: Optional[re.Match] = re.search(r'"completion_tokens": (\d+)', block)
        llm_calls_match: Optional[re.Match] = re.search(r'"successful_requests": (\d+)', block)
        model_names: List[str] = re.findall(r'"(gpt[^"]+|claude[^"]+|gemini[^"]+|o\d[^"]*)"', block)
        total_tokens: int = 0
        if total_match:
            total_tokens = int(total_match.group(1))
        prompt_tokens: int = 0
        if prompt_match:
            prompt_tokens = int(prompt_match.group(1))
        completion_tokens: int = 0
        if completion_match:
            completion_tokens = int(completion_match.group(1))
        llm_calls: int = 0
        if llm_calls_match:
            llm_calls = int(llm_calls_match.group(1))
        model: str = "unknown"
        if model_names:
            model = model_names[0]
        return {
            "request_id": request_id_match.group(1),
            "total_tokens": total_tokens,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "llm_calls": llm_calls,
            "model": model,
        }

    def parse_per_network_tokens_since(self, position) -> List[Dict[str, Any]]:
        """Parse per-sub-network token data from Request reporting blocks.

        For multi-agent networks (e.g. AND), each sub-network produces
        its own Request reporting block followed by a
        "Done with <network>.StreamingChat" log line.  This method
        collects all such blocks and returns one entry per sub-network
        per request.
        """
        if self._server_log is None or position is None:
            return []
        lines: List[str] = self._read_lines_since(position, "network tokens")
        if not lines:
            return []
        blocks: List[Dict[str, object]] = self._collect_reporting_blocks(lines)
        return self._resolve_network_names(blocks, lines)

    @staticmethod
    def _collect_reporting_blocks(lines) -> List[Dict[str, object]]:
        """Collect Request reporting blocks with their line positions."""
        blocks: List[Dict[str, object]] = []
        in_block: bool = False
        block_lines: List[str] = []
        for index, line in enumerate(lines):
            if "Request reporting" in line and not in_block:
                in_block = True
                block_lines = [line]
            elif in_block:
                block_lines.append(line)
                if '"request_id"' in line:
                    blocks.append({"text": "".join(block_lines), "end_idx": index})
                    in_block = False
                    block_lines = []
        return blocks

    @staticmethod
    def _resolve_network_names(blocks, lines) -> List[Dict[str, Any]]:
        """Match each block to its network via Done-with log lines."""
        results: List[Dict[str, Any]] = []
        for block in blocks:
            block_text: str = block.get("text", "")
            entry: Optional[Dict[str, Any]] = ServerLogMonitor._extract_token_entry(block_text)
            if not entry:
                continue
            network: Optional[str] = ServerLogMonitor._find_network_after(lines, block.get("end_idx", 0))
            if not network:
                continue
            duration_match: Optional[re.Match] = re.search(r'"time_taken_in_seconds": ([\d.]+)', block_text)
            total_cost_match: Optional[re.Match] = re.search(r'"total_cost": ([\d.]+)', block_text)
            duration_seconds: float = 0.0
            if duration_match:
                duration_seconds = float(duration_match.group(1))
            total_cost_usd: float = 0.0
            if total_cost_match:
                total_cost_usd = float(total_cost_match.group(1))
            results.append({
                "request_id": entry.get("request_id", ""),
                "network": network,
                "total_tokens": entry.get("total_tokens", 0),
                "prompt_tokens": entry.get("prompt_tokens", 0),
                "completion_tokens": entry.get("completion_tokens", 0),
                "llm_calls": entry.get("llm_calls", 0),
                "duration": duration_seconds,
                "model": entry.get("model", "unknown"),
                "cost": total_cost_usd,
            })
        return results

    @staticmethod
    def _find_network_after(lines, end_idx, lookahead=NETWORK_LOOKAHEAD_LINES) -> Optional[str]:
        """Find the network name from Done-with lines after a block."""
        limit: int = min(end_idx + lookahead, len(lines))
        for index in range(end_idx + 1, limit):
            match: Optional[re.Match] = DONE_STREAMING_PATTERN.search(lines[index])
            if match:
                return match.group(1)
        return None

    def parse_validation_events_since(self, position) -> List[Dict[str, Any]]:
        """Parse validation attempts and fix cycles per request.

        Scans for 'Validating toolbox agents' (attempt),
        'Validation errors' (error detail), and
        'Invoking agent network designer to fix' (fix cycle).
        Groups by request_id.
        """
        if self._server_log is None or position is None:
            return []
        lines: List[str] = self._read_lines_since(position, "validation events")
        if not lines:
            return []
        return self._collect_validation_events(lines)

    @staticmethod
    def _collect_validation_events(lines) -> List[Dict[str, Any]]:
        """Group validation log lines by request_id."""
        by_request: Dict[str, Dict[str, object]] = {}
        for line in lines:
            request_id_match: Optional[re.Match] = VALIDATION_REQUEST_ID_PATTERN.search(line)
            if not request_id_match:
                continue
            request_id: str = request_id_match.group(1)
            if request_id not in by_request:
                by_request[request_id] = {"attempts": 0, "fix_cycles": 0, "errors": []}
            entry: Dict[str, object] = by_request[request_id]
            if VALIDATION_ATTEMPT_PATTERN.search(line):
                entry["attempts"] += 1
            if VALIDATION_REINVOKE_PATTERN.search(line):
                entry["fix_cycles"] += 1
            error_match: Optional[re.Match] = VALIDATION_ERROR_PATTERN.search(line)
            if error_match:
                raw_errors: str = error_match.group(1)
                for error in re.findall(r'"([^"]+)"', raw_errors):
                    entry["errors"].append(error)
        results: List[Dict[str, Any]] = []
        for request_id, data in sorted(by_request.items()):
            if data.get("fix_cycles", 0) > 0:
                results.append({
                    "request_id": request_id,
                    "attempts": data.get("attempts", 0),
                    "fix_cycles": data.get("fix_cycles", 0),
                    "errors": data.get("errors", []),
                })
        return results

    def parse_streaming_chat_timing_since(self, position) -> List[Dict[str, object]]:
        """Parse Start/Finish streaming_chat entries for timing.

        Returns a list of dicts with agent, start_ts, finish_ts,
        duration_seconds, and request_id for each streaming_chat pair.
        """
        if self._server_log is None or position is None:
            return []
        lines: List[str] = self._read_lines_since(position, "streaming_chat timing")
        if not lines:
            return []
        return self._match_streaming_chat_pairs(lines)

    @staticmethod
    def _match_streaming_chat_pairs(lines) -> List[Dict[str, object]]:
        """Match Start/Finish pairs from server log lines."""
        from datetime import datetime  # pylint: disable=import-outside-toplevel

        starts: Dict[Tuple[str, str], float] = {}
        results: List[Dict[str, object]] = []
        for line in lines:
            entry: Any = None
            try:
                entry = json.loads(line.strip())
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(entry, dict):
                continue
            message: str = entry.get("message", "")
            timestamp_text: str = entry.get("Timestamp", "")
            request_id: str = entry.get("request_id", "")
            if not message or not timestamp_text:
                continue
            timestamp_seconds: float = 0.0
            try:
                timestamp_seconds = datetime.fromisoformat(timestamp_text).timestamp()
            except (ValueError, TypeError):
                continue
            agent_path: str = ""
            agent: str = ""
            if message.startswith("Start ") and "/streaming_chat" in message:
                agent_path = message.replace("Start ", "")
                agent = agent_path.replace("/streaming_chat", "")
                starts[(agent, request_id)] = timestamp_seconds
            elif message.startswith("Finish ") and "/streaming_chat" in message:
                agent_path = message.replace("Finish ", "")
                agent = agent_path.replace("/streaming_chat", "")
                start_seconds: Optional[float] = starts.pop((agent, request_id), None)
                if start_seconds is not None:
                    results.append({
                        "agent": agent,
                        "start_ts": start_seconds,
                        "finish_ts": timestamp_seconds,
                        "duration_seconds": timestamp_seconds - start_seconds,
                        "request_id": request_id,
                    })
        return results

    def scan_disconnections_since(self, position, primary_start_pattern=None) -> List[Dict[str, str]]:
        """Scan server log for client disconnections since the given position.

        Returns a list of dicts with request_id, agent, and
        client_request (the originating client request ordinal).
        """
        if self._server_log is None or position is None:
            return []
        lines: List[str] = self._read_lines_since(position, "disconnections")
        if not lines:
            return []

        primary_start_re: Optional[re.Pattern] = None
        if primary_start_pattern:
            primary_start_re = re.compile(primary_start_pattern)
        primary_request_ids: List[str] = []
        disconnections: Dict[str, Dict[str, str]] = {}
        context_request_id: Optional[str] = None

        for line in lines:
            request_match: Optional[re.Match] = STREAM_CLOSED_REQUEST_PATTERN.search(line)
            if request_match:
                context_request_id = request_match.group(1)
            if primary_start_re and primary_start_re.search(line) and context_request_id:
                if context_request_id not in primary_request_ids:
                    primary_request_ids.append(context_request_id)
            if CLIENT_DISCONNECT_PATTERN.search(line):
                request_id: str = context_request_id or "unknown"
                if request_id not in disconnections:
                    disconnections[request_id] = {"request_id": request_id, "agent": "unknown"}
            cancel_match: Optional[re.Match] = TASK_CANCELLED_PATTERN.search(line)
            if cancel_match and context_request_id:
                agent: str = cancel_match.group(1)
                disconnection: Optional[Dict[str, str]] = disconnections.get(context_request_id)
                if disconnection is not None:
                    disconnection.update({"agent": agent})

        self._map_to_client_requests(disconnections, primary_request_ids)
        return list(disconnections.values())

    @staticmethod
    def _map_to_client_requests(disconnections, primary_request_ids):
        """Map each disconnected sub-request to its parent client request.

        Uses sequential server request_id ordering: a sub-request
        belongs to the nearest preceding primary request.
        """
        if not primary_request_ids:
            return

        primary_numbers: List[int] = []
        for primary_request_id in primary_request_ids:
            primary_numbers.append(ServerLogMonitor._request_number(primary_request_id))

        for disconnection in disconnections.values():
            request_id: str = disconnection.get("request_id", "")
            request_number: int = ServerLogMonitor._request_number(request_id)
            parent_index: Optional[int] = None
            for index, primary_number in enumerate(primary_numbers):
                if primary_number <= request_number:
                    parent_index = index
                else:
                    break
            if parent_index is not None:
                disconnection["client_request"] = f"request-{parent_index + 1}"

    @staticmethod
    def _request_number(request_id: str) -> int:
        """
        Read the number at the end of a server request_id, used to put request_ids in order.

        :param request_id: Server request_id
        :return: The number at the end of request_id, or -1 when there is none
        """
        match: Optional[re.Match] = re.search(r"(\d+)$", request_id)
        if match:
            return int(match.group(1))
        return -1

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def start_log_monitor(self, position: Optional[int], expected_count: int, fire_time: float,
                          client_proc: Optional[psutil.Process], primary_start_pattern: str,
                          output_dir: Optional[str] = None,
                          ) -> Tuple[Optional[threading.Event], Optional[threading.Thread], Optional[SharedRef]]:
        """
        Start a background thread to monitor server log for request arrivals.

        :param position: Server log offset to start reading from, or None
        :param expected_count: Number of arrivals to wait for
        :param fire_time: time.perf_counter() value taken when the stage fired
        :param client_proc: Client process for the snapshot once all requests arrive, or None
        :param primary_start_pattern: Regex for the log line of a primary agent request arriving
        :param output_dir: Directory for server_receipts.log, or None for console only
        :return: (stop_event, thread, peak_client_ref), or (None, None, None) if monitoring is not available
        """
        if self._server_log is None or position is None:
            return None, None, None
        stop_event: threading.Event = threading.Event()
        peak_client_ref: SharedRef = SharedRef()
        monitor: threading.Thread = threading.Thread(
            target=ServerLogMonitor._log_monitor_worker,
            args=(self._server_log, position, expected_count, stop_event, fire_time),
            kwargs={
                "client_proc": client_proc,
                "peak_client_ref": peak_client_ref,
                "primary_start_pattern": primary_start_pattern,
                "output_dir": output_dir,
            },
            daemon=True,
        )
        monitor.start()
        return stop_event, monitor, peak_client_ref

    # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    @staticmethod
    def _log_monitor_worker(server_log: str, position: int, expected_count: int, stop_event: threading.Event,
                            fire_time: float, client_proc: Optional[psutil.Process], peak_client_ref: SharedRef,
                            primary_start_pattern: str, output_dir: Optional[str] = None) -> None:
        """
        Background worker that tails server log and reports arrivals.

        :param server_log: Path of the server log
        :param position: Server log offset to start reading from
        :param expected_count: Number of arrivals to wait for
        :param stop_event: Set to stop tailing
        :param fire_time: time.perf_counter() value taken when the stage fired
        :param client_proc: Client process for the snapshot once all requests arrive, or None
        :param peak_client_ref: Receives the client snapshot once all requests arrive
        :param primary_start_pattern: Regex for the log line of a primary agent request arriving
        :param output_dir: Directory for server_receipts.log, or None for console only
        """
        primary_start_re: re.Pattern = re.compile(primary_start_pattern)
        agent_label: str = primary_start_pattern.split("/")[0].split(" ")[-1]
        receipt_path: Optional[str] = None
        if output_dir:
            receipt_path = os.path.join(output_dir, "server_receipts.log")
        try:
            with ServerLogMonitor._open_receipt_log(receipt_path) as receipt_fh:
                with open(server_log, "r", encoding="utf-8") as log_fh:
                    log_fh.seek(position)
                    ServerLogMonitor._tail_arrivals(log_fh, stop_event, primary_start_re, expected_count, fire_time,
                                                    agent_label=agent_label, receipt_fh=receipt_fh,
                                                    client_proc=client_proc, peak_client_ref=peak_client_ref)
        except OSError as exc:
            logger.debug("Log monitor stopped: %s", exc)

    @staticmethod
    def _open_receipt_log(path: Optional[str]) -> Union[TextIO, _NullFile]:
        """
        Open the receipt log file or return a no-op context.

        :param path: Path of server_receipts.log, or None for no file
        :return: The open receipt log, or a no-op context manager when path is None
        """
        if path:
            return open(path, "w", encoding="utf-8")
        return _NullFile()

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    @staticmethod
    def _tail_arrivals(log_fh: TextIO, stop_event: threading.Event, primary_start_re: re.Pattern, expected_count: int,
                       fire_time: float, agent_label: str, receipt_fh: Optional[TextIO],
                       client_proc: Optional[psutil.Process], peak_client_ref: SharedRef) -> None:
        """
        Tail log for arrivals, printing dots or full lines.

        :param log_fh: Open server log, positioned where to start reading
        :param stop_event: Set to stop tailing
        :param primary_start_re: Matches the log line of a primary agent request arriving
        :param expected_count: Number of arrivals to wait for
        :param fire_time: time.perf_counter() value taken when the stage fired
        :param agent_label: Agent name shown in the receipt lines
        :param receipt_fh: Open server_receipts.log, or None to log each receipt to the console
        :param client_proc: Client process for the snapshot once all requests arrive, or None
        :param peak_client_ref: Receives the client snapshot once all requests arrive
        """
        count: int = 0
        use_dots: bool = receipt_fh is not None
        while not stop_event.is_set() and count < expected_count:
            line: str = log_fh.readline()
            if not line:
                stop_event.wait(0.5)
                continue
            if not primary_start_re.search(line):
                continue
            count += 1
            now: float = time.perf_counter()
            timestamp: str = time.strftime("%H:%M:%S", time.localtime())
            delta_seconds: float = now - fire_time
            detail: str = (f"  [server] {agent_label} request {count}/{expected_count} received [{timestamp}]"
                           f" (+{delta_seconds:.1f}s)")
            if use_dots:
                receipt_fh.write(detail + "\n")
                receipt_fh.flush()
                _progress_logger.info(".")
            else:
                logger.info("%s", detail)
            if count >= expected_count:
                ServerLogMonitor._log_all_received(use_dots, count, expected_count, delta_seconds, client_proc,
                                                   peak_client_ref)

    @staticmethod
    def _log_all_received(use_dots, count, expected_count, elapsed_seconds, client_proc, peak_client_ref) -> None:
        """Log the final receipt summary and client snapshot."""
        if use_dots:
            _progress_logger.info("\n")
            logger.info("  All %s/%s requests received by server (%.1fs)", count, expected_count, elapsed_seconds)
        snapshot: Optional[Dict[str, Any]] = ResourceMonitor.snapshot(client_proc)
        if snapshot:
            logger.info("  Client AFTER: RSS %.1fM, CPU %.1f%%", snapshot.get("rss"), snapshot.get("cpu"))
            peak_client_ref.value = snapshot
        virtual_memory_stats: Any = psutil.virtual_memory()
        used_megabytes: float = (virtual_memory_stats.total - virtual_memory_stats.available) / (1024 ** 2)
        available_gigabytes: float = virtual_memory_stats.available / (1024 ** 3)
        total_gigabytes: float = virtual_memory_stats.total / (1024 ** 3)
        logger.info("  System RECEIVED: %.0f%% used (%.0fM used / %.1fG free / %.1fG total)",
                    virtual_memory_stats.percent, used_megabytes, available_gigabytes, total_gigabytes)
