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

# Plain "import re": "from re import compile" would hide the builtin compile().
import re
from json import JSONDecodeError
from json import loads
from logging import Logger
from logging import getLogger
from threading import Event
from threading import Thread
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from leaf_common.logging.sensitive_logger import SensitiveLogger
from psutil import Process

from tests.load_tests.load_test_constants import LoadTestConstants
from tests.load_tests.monitoring.arrival_watcher import ArrivalWatcher
from tests.load_tests.monitoring.server_log_parser import ServerLogParser


class ServerLogMonitor:
    """
    Parses a neuro-san server log for retries, tokens, and disconnections.

    Covers retry counting, request tracking, and disconnection scanning.
    Holds the server log path so that callers do not need to pass it
    to every method.

    Interim implementation. May be replaced by neuro-san built-in
    monitoring and telemetry when those features become available.
    """

    def __init__(self, server_log: Optional[str]) -> None:
        """
        Store the server log path.

        :param server_log: Path of the server log, or None when there is none
        """
        self.logger: Logger = getLogger(self.__class__.__name__)
        self._parser: ServerLogParser = ServerLogParser()
        self._server_log: Optional[str] = server_log

    def read_position(self) -> Optional[int]:
        """
        Return the current end position of the server log file.

        :return: The end position, or None when there is no server log or it can't be read
        """
        if self._server_log is None:
            return None
        try:
            with open(self._server_log, "r", encoding="utf-8") as server_log_file:
                server_log_file.seek(0, 2)
                return server_log_file.tell()
        except OSError:
            return None

    def count_retries_since(self, position: Optional[int]) -> Dict[str, int]:
        """
        Count retry log entries since the given position.

        Covers both neuro-san's own max_attempts retries ("Retrying:
        <reason> (<ErrorType>) - <error>") and retries the LLM provider SDK performs
        internally ("Retrying request to ... in ... seconds"), counted
        under the "ProviderRetry" key.  The latter are invisible to
        neuro-san but are still extra LLM attempts, so they belong in
        the amplification factor.

        :param position: Server log position to read from, from read_position(), or None
        :return: A dict of error_type -> count for each tracked type
        """
        if self._server_log is None or position is None:
            return {}
        lines: List[str] = self._read_lines_since(position, "retries")
        retry_counts: Dict[str, int] = {}
        line: str
        # Count each retry line by its error type.
        for line in lines:
            match: Optional[re.Match] = LoadTestConstants.RETRY_LOG_PATTERN.search(line)
            if match:
                error_type: str = match.group(1)
                retry_counts[error_type] = retry_counts.get(error_type, 0) + 1
            elif LoadTestConstants.PROVIDER_RETRY_PATTERN.search(line):
                retry_counts["ProviderRetry"] = retry_counts.get("ProviderRetry", 0) + 1
        return retry_counts

    def scan_server_errors_since(self, position: Optional[int]) -> List[Dict[str, str]]:
        """
        Scan for server "Errors detected:" events since position.

        These are logged as JSON with a "message" value that starts
        with "Errors detected:" and spans literal newlines, so the log
        window is joined and matched with a DOTALL pattern.

        :param position: Server log position to read from, from read_position(), or None
        :return: A list of {request_id, message} dicts with the message flattened
                 to a single line
        """
        if self._server_log is None or position is None:
            return []
        lines: List[str] = self._read_lines_since(position, "errors")
        if not lines:
            return []
        log_text: str = "".join(lines)
        errors: List[Dict[str, str]] = []
        match: re.Match
        # One error entry per server error block in the new text.
        for match in LoadTestConstants.SERVER_ERROR_PATTERN.finditer(log_text):
            message_words: List[str] = match.group(1).split()
            message: str = " ".join(message_words)
            error_request_id: str = match.group(2)
            errors.append({
                "request_id": error_request_id,
                "message": message,
            })
        return errors

    def scan_tool_warnings_since(self, position: Optional[int]) -> List[Dict[str, str]]:
        """
        Scan for "Failed to create Agent/tool" warnings since position.

        These are logged as one-line JSON with message_type "Warning"
        and mean a requested tool (e.g. web_search) was unavailable to
        an agent.  They do not affect the created network, but a high
        count under load may point to tool-creation failures.

        :param position: Server log position to read from, from read_position(), or None
        :return: A list of {request_id, message} dicts
        """
        if self._server_log is None or position is None:
            return []
        lines: List[str] = self._read_lines_since(position, "tool warnings")
        warnings: List[Dict[str, str]] = []
        line: str
        # Keep each "Failed to create Agent/tool" entry as one warning.
        for line in lines:
            stripped: str = line.strip()
            if "Failed to create Agent/tool" not in stripped:
                continue
            entry: Any = None
            try:
                entry = loads(stripped)
            except (JSONDecodeError, ValueError):
                continue
            if not isinstance(entry, dict):
                continue
            entry_dict: Dict[str, Any] = entry
            message: str = entry_dict.get("message", "")
            if not message.startswith("Failed to create Agent/tool"):
                continue
            message_words: List[str] = message.split()
            warning_message: str = " ".join(message_words)
            warning: Dict[str, str] = {
                "request_id": entry_dict.get("request_id", "unknown"),
                "message": warning_message,
            }
            warnings.append(warning)
        return warnings

    def count_requests_since(self, position: Optional[int], primary_start_pattern: str,
                             primary_finish_pattern: str) -> Dict[str, Optional[int]]:
        """
        Count request Start/Finish entries since the given position.

        Uses agent-specific patterns for primary requests.

        :param position: Server log position to read from, from read_position(), or None
        :param primary_start_pattern: Pattern for the primary agent's Start line
        :param primary_finish_pattern: Pattern for the primary agent's Finish line
        :return: A dict with "primary_started", "primary_finished", "total_started" and "total_finished"
                 counts, all None when there is no server log or position, or no lines since position
        """
        none_result: Dict[str, Optional[int]] = {
            "primary_started": None,
            "primary_finished": None,
            "total_started": None,
            "total_finished": None,
        }
        if self._server_log is None or position is None:
            return none_result
        lines: List[str] = self._read_lines_since(position, "counts")
        if not lines:
            return none_result
        primary_started: int = 0
        primary_finished: int = 0
        total_started: int = 0
        total_finished: int = 0
        primary_start_regex: re.Pattern = re.compile(primary_start_pattern)
        primary_finish_regex: re.Pattern = re.compile(primary_finish_pattern)
        line: str
        # Count the request start and finish lines, for all requests and for primary requests.
        for line in lines:
            if LoadTestConstants.REQUEST_START_PATTERN.search(line):
                total_started += 1
            if LoadTestConstants.REQUEST_FINISH_PATTERN.search(line):
                total_finished += 1
            if primary_start_regex.search(line):
                primary_started += 1
            if primary_finish_regex.search(line):
                primary_finished += 1
        request_counts: Dict[str, Optional[int]] = {
            "primary_started": primary_started,
            "primary_finished": primary_finished,
            "total_started": total_started,
            "total_finished": total_finished,
        }
        return request_counts

    def parse_token_accounting_since(self, position: Optional[int]) -> Dict[str, Dict[str, Any]]:
        """
        Parse Request reporting entries for token accounting data.

        :param position: Server log position to read from, from read_position(), or None
        :return: A dict of request_id -> token entry. Each entry has "request_id", "total_tokens",
                 "prompt_tokens", "completion_tokens", "llm_calls" and "model", plus "reporting_agent"
                 when a Done-with line follows the block
        """
        if self._server_log is None or position is None:
            return {}
        lines: List[str] = self._read_lines_since(position, "tokens")
        if not lines:
            return {}
        results: Dict[str, Dict[str, Any]] = {}
        block: Dict[str, object]
        # Keep the token entry of each reporting block, with the network named after it.
        for block in self._parser.collect_reporting_blocks(lines):
            block_text: str = block.get("text", "")
            entry: Optional[Dict[str, Any]] = self._parser.extract_token_entry(block_text)
            if entry:
                request_id: Optional[str] = entry.get("request_id")
                if request_id is not None:
                    end_index: int = block.get("end_index", 0)
                    agent: Optional[str] = self._parser.find_network_after(lines, end_index)
                    if agent:
                        entry["reporting_agent"] = agent
                    results[request_id] = entry
        return results

    def parse_per_network_tokens_since(self, position: Optional[int]) -> List[Dict[str, Any]]:
        """
        Parse per-sub-network token data from Request reporting blocks.

        For multi-agent networks (e.g. AND), each sub-network produces
        its own Request reporting block followed by a
        "Done with <network>.StreamingChat" log line.  This method
        collects all such blocks and returns one entry per sub-network
        per request.

        :param position: Server log position to read from, from read_position(), or None
        :return: One dict per sub-network block that has a network name, with the keys listed in
                 self._parser.resolve_network_names()
        """
        if self._server_log is None or position is None:
            return []
        lines: List[str] = self._read_lines_since(position, "network tokens")
        if not lines:
            return []
        blocks: List[Dict[str, object]] = self._parser.collect_reporting_blocks(lines)
        return self._parser.resolve_network_names(blocks, lines)

    def parse_validation_events_since(self, position: Optional[int]) -> List[Dict[str, Any]]:
        """
        Parse validation attempts and fix cycles per request.

        Scans for 'Validating toolbox agents' (attempt),
        'Validation errors' (error detail), and
        'Invoking agent network designer to fix' (fix cycle).
        Groups by request_id.

        :param position: Server log position to read from, from read_position(), or None
        :return: One dict with "request_id", "attempts", "fix_cycles" and "errors" for each request that
                 needed a fix cycle, sorted by request_id
        """
        if self._server_log is None or position is None:
            return []
        lines: List[str] = self._read_lines_since(position, "validation events")
        if not lines:
            return []
        return self._parser.collect_validation_events(lines)

    def parse_streaming_chat_timing_since(self, position: Optional[int]) -> List[Dict[str, object]]:
        """
        Parse Start/Finish streaming_chat entries for timing.

        :param position: Server log position to read from, from read_position(), or None
        :return: A list of dicts with agent, start_ts, finish_ts,
                 duration_seconds, and request_id for each streaming_chat pair
        """
        if self._server_log is None or position is None:
            return []
        lines: List[str] = self._read_lines_since(position, "streaming_chat timing")
        if not lines:
            return []
        return self._parser.match_streaming_chat_pairs(lines)

    def scan_disconnections_since(self, position: Optional[int],
                                  primary_start_pattern: Optional[str] = None) -> List[Dict[str, str]]:
        """
        Scan server log for client disconnections since the given position.

        :param position: Server log position to read from, from read_position(), or None
        :param primary_start_pattern: Pattern for the primary agent's Start line, or None
        :return: A list of dicts with request_id, agent (from the
                 request's "Start <agent>/streaming_chat" line, once its task
                 is cancelled), and client_request (the originating client
                 request ordinal); "client_request" is set only when a primary request comes before it
        """
        if self._server_log is None or position is None:
            return []
        lines: List[str] = self._read_lines_since(position, "disconnections")
        if not lines:
            return []

        primary_start_regex: Optional[re.Pattern] = None
        if primary_start_pattern:
            primary_start_regex = re.compile(primary_start_pattern)
        primary_request_ids: List[str] = []
        disconnections: Dict[str, Dict[str, str]] = {}
        context_request_id: Optional[str] = None
        agent_by_request_id: Dict[str, str] = {}

        line: str
        # Track the current request_id and record primary requests, disconnections and cancels.
        for line in lines:
            request_match: Optional[re.Match] = LoadTestConstants.REQUEST_ID_PATTERN.search(line)
            if request_match:
                context_request_id = request_match.group(1)
            start_match: Optional[re.Match] = LoadTestConstants.REQUEST_START_PATTERN.search(line)
            if start_match and request_match:
                agent_by_request_id[request_match.group(1)] = start_match.group(1)
            if (primary_start_regex
                    and primary_start_regex.search(line)
                    and context_request_id):
                if context_request_id not in primary_request_ids:
                    primary_request_ids.append(context_request_id)
            if LoadTestConstants.CLIENT_DISCONNECT_PATTERN.search(line):
                request_id: str = context_request_id or "unknown"
                # pylint: disable=consider-iterating-dictionary
                if request_id not in disconnections.keys():
                    disconnections[request_id] = {
                        "request_id": request_id,
                        "agent": "unknown",
                    }
            cancel_match: Optional[re.Match] = LoadTestConstants.TASK_CANCELLED_PATTERN.search(line)
            if cancel_match:
                self._parser.set_cancelled_agent(cancel_match, disconnections, agent_by_request_id)

        self._parser.map_to_client_requests(disconnections, primary_request_ids)
        return self._parser.disconnection_list(disconnections)

    def start_log_monitor(self, monitor_settings: Dict[str, Any]) -> Optional[Thread]:
        """
        Start a background thread to monitor server log for request arrivals.

        :param monitor_settings: A dict with the following keys:
            "position"               Server log position from read_position() to start reading from, or None
            "expected_count"         Number of arrivals to wait for
            "fire_time_seconds"      time.perf_counter() value in seconds taken when the stage fired
            "stop_event"             Event that tells the monitor thread to stop
            "client_process"         Client process for the snapshot once all requests arrive, or None
            "primary_start_pattern"  Regex for the log line of a primary agent request arriving
            "output_dir"             Directory for server_receipts.log, or None for console only
        :return: The started monitor thread, or None if monitoring is not available
        """
        position: Optional[int] = monitor_settings.get("position")
        if self._server_log is None or position is None:
            return None
        expected_count: int = monitor_settings.get("expected_count")
        fire_time_seconds: float = monitor_settings.get("fire_time_seconds")
        stop_event: Event = monitor_settings.get("stop_event")
        client_process: Optional[Process] = monitor_settings.get("client_process")
        primary_start_pattern: str = monitor_settings.get("primary_start_pattern")
        output_dir: Optional[str] = monitor_settings.get("output_dir")
        arrival_settings: Dict[str, Any] = {
            "expected_count": expected_count,
            "fire_time_seconds": fire_time_seconds,
            "stop_event": stop_event,
            "client_process": client_process,
            "primary_start_pattern": primary_start_pattern,
        }
        watcher: ArrivalWatcher = ArrivalWatcher(arrival_settings)
        return watcher.start(self._server_log, position, output_dir)

    def _read_lines_since(self, position: int, label: str) -> List[str]:
        """
        Read all lines from server_log starting at the given position.

        :param position: Server log position to read from, from read_position()
        :param label: What is being read, for the log message when an OSError occurs
        :return: The lines, or an empty list on read failure
        """
        try:
            with open(self._server_log, "r", encoding="utf-8") as server_log_file:
                server_log_file.seek(position)
                return server_log_file.readlines()
        except OSError as exc:
            sensitive_logger: SensitiveLogger = SensitiveLogger(self.logger)
            sensitive_logger.info("Could not read server log for %s: %s", label, exc)
            return []
