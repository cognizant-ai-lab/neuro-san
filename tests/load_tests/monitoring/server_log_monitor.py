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

import json
import logging
import os
import re
import sys
import threading
import time

from datetime import datetime
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import TextIO
from typing import Tuple
from typing import Union

import psutil

from tests.load_tests.load_test_constants import CLIENT_DISCONNECT_PATTERN
from tests.load_tests.load_test_constants import DONE_STREAMING_PATTERN
from tests.load_tests.load_test_constants import NETWORK_LOOKAHEAD_LINES
from tests.load_tests.load_test_constants import PROVIDER_RETRY_PATTERN
from tests.load_tests.load_test_constants import REQUEST_FINISH_PATTERN
from tests.load_tests.load_test_constants import REQUEST_ID_PATTERN
from tests.load_tests.load_test_constants import REQUEST_START_PATTERN
from tests.load_tests.load_test_constants import RETRY_LOG_PATTERN
from tests.load_tests.load_test_constants import SERVER_ERROR_PATTERN
from tests.load_tests.load_test_constants import TASK_CANCELLED_PATTERN
from tests.load_tests.load_test_constants import VALIDATION_ATTEMPT_PATTERN
from tests.load_tests.load_test_constants import VALIDATION_ERROR_ITEM_PATTERN
from tests.load_tests.load_test_constants import VALIDATION_ERROR_PATTERN
from tests.load_tests.load_test_constants import VALIDATION_REINVOKE_PATTERN
from tests.load_tests.monitoring.resource_monitor import ResourceMonitor

logger: logging.Logger = logging.getLogger(__name__)

# Console progress ticks for arrivals: single-line dots written via
# logging (not print()).  An empty terminator keeps the dots on one
# line, and propagate=False stops the root logger from prefixing each
# dot with a timestamp or duplicating it.
_progress_logger: logging.Logger = logging.getLogger(__name__ + ".progress")
_progress_logger.propagate = False
if not _progress_logger.handlers:
    _progress_handler = logging.StreamHandler(sys.stdout)
    _progress_handler.terminator = ""
    _progress_handler.setFormatter(logging.Formatter("%(message)s"))
    _progress_logger.addHandler(_progress_handler)
    _progress_logger.setLevel(logging.INFO)


class _NullFile:
    """
    No-op context manager used when no receipt file is needed.
    """

    def __enter__(self):
        """
        Enter the context without opening a file.
        """
        return None

    def __exit__(self, *args):
        """
        Leave the context; there is no file to close.

        :param args: Exception type, value and traceback (not used)
        """


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

    def _read_lines_since(self, position, label) -> List[str]:
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
            logger.info("Could not read server log for %s: %s", label, exc)
            return []

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
            match: Optional[re.Match] = RETRY_LOG_PATTERN.search(line)
            if match:
                error_type: str = match.group(1)
                retry_counts[error_type] = retry_counts.get(error_type, 0) + 1
            elif PROVIDER_RETRY_PATTERN.search(line):
                retry_counts["ProviderRetry"] = retry_counts.get("ProviderRetry", 0) + 1
        return retry_counts

    def scan_server_errors_since(self, position) -> List[Dict[str, str]]:
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
        for match in SERVER_ERROR_PATTERN.finditer(log_text):
            message_words: List[str] = match.group(1).split()
            message: str = " ".join(message_words)
            errors.append({"request_id": match.group(2), "message": message})
        return errors

    def scan_tool_warnings_since(self, position) -> List[Dict[str, str]]:
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
                entry = json.loads(stripped)
            except (json.JSONDecodeError, ValueError):
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

    def count_requests_since(self, position, primary_start_pattern, primary_finish_pattern) -> Dict[str, Optional[int]]:
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
        primary_start_re: re.Pattern = re.compile(primary_start_pattern)
        primary_finish_re: re.Pattern = re.compile(primary_finish_pattern)
        line: str
        # Count the request start and finish lines, for all requests and for primary requests.
        for line in lines:
            if REQUEST_START_PATTERN.search(line):
                total_started += 1
            if REQUEST_FINISH_PATTERN.search(line):
                total_finished += 1
            if primary_start_re.search(line):
                primary_started += 1
            if primary_finish_re.search(line):
                primary_finished += 1
        request_counts: Dict[str, Optional[int]] = {
            "primary_started": primary_started,
            "primary_finished": primary_finished,
            "total_started": total_started,
            "total_finished": total_finished,
        }
        return request_counts

    def parse_token_accounting_since(self, position) -> Dict[str, Dict[str, Any]]:
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
        for block in self._collect_reporting_blocks(lines):
            block_text: str = block.get("text", "")
            entry: Optional[Dict[str, Any]] = self._extract_token_entry(block_text)
            if entry:
                request_id: Optional[str] = entry.get("request_id")
                if request_id is not None:
                    end_idx: int = block.get("end_idx", 0)
                    agent: Optional[str] = self._find_network_after(lines, end_idx)
                    if agent:
                        entry["reporting_agent"] = agent
                    results[request_id] = entry
        return results

    @staticmethod
    def _int_group(match: Optional[re.Match]) -> int:
        """
        Read group 1 of a regex match as an int.

        :param match: The match, or None
        :return: The number, or 0 when there is no match
        """
        number: int = 0
        if match:
            number_text: str = match.group(1)
            number = int(number_text)
        return number

    @staticmethod
    def _extract_token_entry(block: str) -> Optional[Dict[str, Any]]:
        """
        Extract token accounting fields from a Request reporting log block.

        :param block: Text of one Request reporting log block
        :return: A dict with "request_id", "total_tokens", "prompt_tokens", "completion_tokens", "llm_calls"
                 and "model", or None when the block has no request_id
        """
        request_id_match: Optional[re.Match] = re.search(r'"request_id": "([^"]+)"', block)
        if not request_id_match:
            return None
        total_match: Optional[re.Match] = re.search(r'"total_tokens": (\d+)', block)
        prompt_match: Optional[re.Match] = re.search(r'"prompt_tokens": (\d+)', block)
        completion_match: Optional[re.Match] = re.search(r'"completion_tokens": (\d+)', block)
        llm_calls_match: Optional[re.Match] = re.search(r'"successful_requests": (\d+)', block)
        # Pulls model names that start with gpt, claude, gemini or o<digit>
        model_names: List[str] = re.findall(r'"(gpt[^"]+|claude[^"]+|gemini[^"]+|o\d[^"]*)"', block)
        total_tokens: int = ServerLogMonitor._int_group(total_match)
        prompt_tokens: int = ServerLogMonitor._int_group(prompt_match)
        completion_tokens: int = ServerLogMonitor._int_group(completion_match)
        llm_calls: int = ServerLogMonitor._int_group(llm_calls_match)
        model: str = "unknown"
        if model_names:
            model = model_names[0]
        token_entry: Dict[str, Any] = {
            "request_id": request_id_match.group(1),
            "total_tokens": total_tokens,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "llm_calls": llm_calls,
            "model": model,
        }
        return token_entry

    def parse_per_network_tokens_since(self, position) -> List[Dict[str, Any]]:
        """
        Parse per-sub-network token data from Request reporting blocks.

        For multi-agent networks (e.g. AND), each sub-network produces
        its own Request reporting block followed by a
        "Done with <network>.StreamingChat" log line.  This method
        collects all such blocks and returns one entry per sub-network
        per request.

        :param position: Server log position to read from, from read_position(), or None
        :return: One dict per sub-network block that has a network name, with the keys listed in
                 _resolve_network_names()
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
        """
        Collect Request reporting blocks with their line positions.

        :param lines: Server log lines
        :return: One dict per Request reporting block, with "text" (its lines joined) and "end_idx"
                 (index of its "request_id" line)
        """
        blocks: List[Dict[str, object]] = []
        in_block: bool = False
        block_lines: List[str] = []
        index: int
        line: str
        # Gather the lines from each "Request reporting" line to its "request_id" line.
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
        """
        Match each block to its network via Done-with log lines.

        :param blocks: Blocks from _collect_reporting_blocks()
        :param lines: Server log lines
        :return: One dict per block that has a token entry and a network name, with "request_id",
                 "network", "total_tokens", "prompt_tokens", "completion_tokens", "llm_calls", "duration",
                 "model" and "cost"
        """
        results: List[Dict[str, Any]] = []
        block: Dict[str, object]
        # Keep each block's token entry with the network named after it.
        for block in blocks:
            block_text: str = block.get("text", "")
            entry: Optional[Dict[str, Any]] = ServerLogMonitor._extract_token_entry(block_text)
            if not entry:
                continue
            end_idx: int = block.get("end_idx", 0)
            network: Optional[str] = ServerLogMonitor._find_network_after(lines, end_idx)
            if not network:
                continue
            duration_match: Optional[re.Match] = re.search(r'"time_taken_in_seconds": ([\d.]+)', block_text)
            total_cost_match: Optional[re.Match] = re.search(r'"total_cost": ([\d.]+)', block_text)
            duration_seconds: float = 0.0
            if duration_match:
                duration_text: str = duration_match.group(1)
                duration_seconds = float(duration_text)
            total_cost_usd: float = 0.0
            if total_cost_match:
                total_cost_text: str = total_cost_match.group(1)
                total_cost_usd = float(total_cost_text)
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
    def _find_network_after(lines: List[str], end_idx: int,
                            lookahead_lines: int = NETWORK_LOOKAHEAD_LINES) -> Optional[str]:
        """
        Find the network name from Done-with lines after a block.

        :param lines: Server log lines
        :param end_idx: Index of the last line of the block
        :param lookahead_lines: The search stops before line end_idx + lookahead_lines, so it checks
                                lookahead_lines - 1 lines after the block
        :return: The network name, or None when no Done-with line is found
        """
        line_count: int = len(lines)
        limit: int = min(end_idx + lookahead_lines, line_count)
        index: int
        # Look for a Done-with line in the lines after the block.
        for index in range(end_idx + 1, limit):
            match: Optional[re.Match] = DONE_STREAMING_PATTERN.search(lines[index])
            if match:
                return match.group(1)
        return None

    def parse_validation_events_since(self, position) -> List[Dict[str, Any]]:
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
        return self._collect_validation_events(lines)

    @staticmethod
    def _collect_validation_events(lines: List[str]) -> List[Dict[str, Any]]:
        """
        Group validation log lines by request_id.

        :param lines: Server log lines
        :return: One dict with "request_id", "attempts", "fix_cycles" and "errors" for each request that
                 needed a fix cycle, sorted by request_id
        """
        by_request: Dict[str, Dict[str, object]] = {}
        request_id: str = ""
        line: str
        # Count validation attempts, fix cycles and errors per request_id.
        for line in lines:
            request_id_match: Optional[re.Match] = REQUEST_ID_PATTERN.search(line)
            if not request_id_match:
                continue
            request_id = request_id_match.group(1)
            # pylint: disable=consider-iterating-dictionary
            if request_id not in by_request.keys():
                by_request[request_id] = {"attempts": 0, "fix_cycles": 0, "errors": []}
            entry: Dict[str, object] = by_request.get(request_id)
            if VALIDATION_ATTEMPT_PATTERN.search(line):
                entry["attempts"] = entry.get("attempts", 0) + 1
            if VALIDATION_REINVOKE_PATTERN.search(line):
                entry["fix_cycles"] = entry.get("fix_cycles", 0) + 1
            error_match: Optional[re.Match] = VALIDATION_ERROR_PATTERN.search(line)
            if error_match:
                error_list_text: str = error_match.group(1)
                validation_errors: List[str] = ServerLogMonitor._parse_validation_errors(error_list_text)
                entry.get("errors").extend(validation_errors)
        results: List[Dict[str, Any]] = []
        validation_entry: Dict[str, object] = {}
        request_ids: List[str] = []
        # Collect the request ids, then sort them.
        # pylint: disable=consider-iterating-dictionary
        for request_id in by_request.keys():
            request_ids.append(request_id)
        request_ids.sort()
        # Keep only the requests that needed a fix cycle, in request_id order.
        for request_id in request_ids:
            validation_entry = by_request.get(request_id)
            fix_cycles: int = validation_entry.get("fix_cycles", 0)
            if fix_cycles > 0:
                results.append({
                    "request_id": request_id,
                    "attempts": validation_entry.get("attempts", 0),
                    "fix_cycles": fix_cycles,
                    "errors": validation_entry.get("errors", []),
                })
        return results

    @staticmethod
    def _parse_validation_errors(error_list_text: str) -> List[str]:
        """
        Read the errors out of the list text the neuro-san-studio middleware logs with "Validation errors: %s".
        Python writes each error in single quotes, or in double quotes when it holds a single quote.
        The text is only matched with VALIDATION_ERROR_ITEM_PATTERN, never evaluated.

        :param error_list_text: The list text with its brackets, e.g. "['Missing front man']"
        :return: The errors, or the whole text as one error when no quoted error is found in a non-empty list
        """
        errors: List[str] = []
        single_quoted: str
        double_quoted: str
        # Each match fills only the group of the quote Python chose for that error.
        for single_quoted, double_quoted in VALIDATION_ERROR_ITEM_PATTERN.findall(error_list_text):
            errors.append(single_quoted or double_quoted)
        if not errors and error_list_text != "[]":
            logger.info("Could not find a quoted error in the validation errors %s", error_list_text)
            errors.append(error_list_text)
        return errors

    def parse_streaming_chat_timing_since(self, position) -> List[Dict[str, object]]:
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
        return self._match_streaming_chat_pairs(lines)

    @staticmethod
    def _match_streaming_chat_pairs(lines) -> List[Dict[str, object]]:
        """
        Match Start/Finish pairs from server log lines.

        :param lines: Server log lines
        :return: One dict per Start/Finish pair
        """
        starts: Dict[Tuple[str, str], float] = {}
        results: List[Dict[str, object]] = []
        line: str
        # Pair each streaming_chat Start record with its Finish record.
        for line in lines:
            entry: Any = None
            try:
                stripped_line: str = line.strip()
                entry = json.loads(stripped_line)
            except (json.JSONDecodeError, ValueError):
                continue
            if not isinstance(entry, dict):
                continue
            entry_dict: Dict[str, Any] = entry
            message: str = entry_dict.get("message", "")
            timestamp_text: str = entry_dict.get("Timestamp", "")
            request_id: str = entry_dict.get("request_id", "")
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

        primary_start_re: Optional[re.Pattern] = None
        if primary_start_pattern:
            primary_start_re = re.compile(primary_start_pattern)
        primary_request_ids: List[str] = []
        disconnections: Dict[str, Dict[str, str]] = {}
        context_request_id: Optional[str] = None
        agent_by_request_id: Dict[str, str] = {}

        line: str
        # Track the current request_id and record primary requests, disconnections and cancels.
        for line in lines:
            request_match: Optional[re.Match] = REQUEST_ID_PATTERN.search(line)
            if request_match:
                context_request_id = request_match.group(1)
            start_match: Optional[re.Match] = REQUEST_START_PATTERN.search(line)
            if start_match and request_match:
                agent_by_request_id[request_match.group(1)] = start_match.group(1)
            if (primary_start_re
                    and primary_start_re.search(line)
                    and context_request_id):
                if context_request_id not in primary_request_ids:
                    primary_request_ids.append(context_request_id)
            if CLIENT_DISCONNECT_PATTERN.search(line):
                request_id: str = context_request_id or "unknown"
                # pylint: disable=consider-iterating-dictionary
                if request_id not in disconnections.keys():
                    disconnections[request_id] = {"request_id": request_id, "agent": "unknown"}
            cancel_match: Optional[re.Match] = TASK_CANCELLED_PATTERN.search(line)
            if cancel_match:
                ServerLogMonitor._set_cancelled_agent(cancel_match, disconnections, agent_by_request_id)

        self._map_to_client_requests(disconnections, primary_request_ids)
        return ServerLogMonitor._disconnection_list(disconnections)

    @staticmethod
    def _disconnection_list(disconnections: Dict[str, Dict[str, str]]) -> List[Dict[str, str]]:
        """
        List the disconnections in first-seen order.

        :param disconnections: The disconnections by request id
        :return: The disconnection dicts, in first-seen order
        """
        disconnection_list: List[Dict[str, str]] = []
        disconnection: Dict[str, str]
        # Keep the disconnections in first-seen order.
        for disconnection in disconnections.values():
            disconnection_list.append(disconnection)
        return disconnection_list

    @staticmethod
    def _set_cancelled_agent(cancel_match: re.Match, disconnections: Dict[str, Dict[str, str]],
                             agent_by_request_id: Dict[str, str]) -> None:
        """
        Put the agent of a cancelled streaming_chat task on its disconnection, if that request disconnected.
        The task is submitted under its request id, so group 1 of the cancel line names the request.

        :param cancel_match: The TASK_CANCELLED_PATTERN match of the cancel line
        :param disconnections: The disconnections found so far, by request id
        :param agent_by_request_id: The agent of each request, from its "Start <agent>/streaming_chat" line
        """
        cancelled_request_id: str = cancel_match.group(1)
        disconnection: Optional[Dict[str, str]] = disconnections.get(cancelled_request_id)
        if disconnection is not None:
            disconnection.update({"agent": agent_by_request_id.get(cancelled_request_id, "unknown")})

    @staticmethod
    def _map_to_client_requests(disconnections, primary_request_ids):
        """
        Map each disconnected sub-request to its parent client request.

        Uses sequential server request_id ordering: a sub-request
        belongs to the nearest preceding primary request.

        :param disconnections: The disconnections by request_id, updated in place
        :param primary_request_ids: Request ids of the primary requests, in log order
        """
        if not primary_request_ids:
            return

        primary_numbers: List[int] = []
        primary_request_id: str
        # Get the request number of each primary request.
        for primary_request_id in primary_request_ids:
            primary_number: int = ServerLogMonitor._request_number(primary_request_id)
            primary_numbers.append(primary_number)

        disconnection: Dict[str, str]
        # Find the client request that each disconnection belongs to.
        for disconnection in disconnections.values():
            request_id: str = disconnection.get("request_id", "")
            request_number: int = ServerLogMonitor._request_number(request_id)
            parent_index: Optional[int] = None
            index: int
            primary_number: int
            # The parent is the last primary request at or before this request number.
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
    def start_log_monitor(self, position: Optional[int], expected_count: int, fire_time_seconds: float,
                          stop_event: threading.Event, client_process: Optional[psutil.Process],
                          primary_start_pattern: str, output_dir: Optional[str] = None) -> Optional[threading.Thread]:
        """
        Start a background thread to monitor server log for request arrivals.

        :param position: Server log offset to start reading from, or None
        :param expected_count: Number of arrivals to wait for
        :param fire_time_seconds: time.perf_counter() value taken when the stage fired
        :param stop_event: Event that tells the monitor thread to stop
        :param client_process: Client process for the snapshot once all requests arrive, or None
        :param primary_start_pattern: Regex for the log line of a primary agent request arriving
        :param output_dir: Directory for server_receipts.log, or None for console only
        :return: The started monitor thread, or None if monitoring is not available
        """
        if self._server_log is None or position is None:
            return None
        monitor: threading.Thread = threading.Thread(
            target=ServerLogMonitor._log_monitor_worker,
            args=[self._server_log, position, expected_count, stop_event, fire_time_seconds],
            kwargs={
                "client_process": client_process,
                "primary_start_pattern": primary_start_pattern,
                "output_dir": output_dir,
            },
            daemon=True,
        )
        monitor.start()
        return monitor

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    @staticmethod
    def _log_monitor_worker(server_log: str, position: int, expected_count: int, stop_event: threading.Event,
                            fire_time_seconds: float, client_process: Optional[psutil.Process],
                            primary_start_pattern: str, output_dir: Optional[str] = None) -> None:
        """
        Background worker that tails server log and reports arrivals.

        :param server_log: Path of the server log
        :param position: Server log offset to start reading from
        :param expected_count: Number of arrivals to wait for
        :param stop_event: Set to stop tailing
        :param fire_time_seconds: time.perf_counter() value taken when the stage fired
        :param client_process: Client process for the snapshot once all requests arrive, or None
        :param primary_start_pattern: Regex for the log line of a primary agent request arriving
        :param output_dir: Directory for server_receipts.log, or None for console only
        """
        primary_start_re: re.Pattern = re.compile(primary_start_pattern)
        agent_label: str = primary_start_pattern.split("/")[0].split(" ")[-1]
        receipt_path: Optional[str] = None
        if output_dir:
            receipt_path = os.path.join(output_dir, "server_receipts.log")
        try:
            with ServerLogMonitor._open_receipt_log(receipt_path) as receipt_file:
                with open(server_log, "r", encoding="utf-8") as server_log_file:
                    server_log_file.seek(position)
                    ServerLogMonitor._tail_arrivals(server_log_file, stop_event, primary_start_re, expected_count,
                                                    fire_time_seconds, agent_label=agent_label,
                                                    receipt_file=receipt_file, client_process=client_process)
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
    def _tail_arrivals(server_log_file: TextIO, stop_event: threading.Event, primary_start_re: re.Pattern,
                       expected_count: int, fire_time_seconds: float, agent_label: str, receipt_file: Optional[TextIO],
                       client_process: Optional[psutil.Process]) -> None:
        """
        Tail log for arrivals, printing dots or full lines.

        :param server_log_file: Open server log, positioned where to start reading
        :param stop_event: Set to stop tailing
        :param primary_start_re: Matches the log line of a primary agent request arriving
        :param expected_count: Number of arrivals to wait for
        :param fire_time_seconds: time.perf_counter() value taken when the stage fired
        :param agent_label: Agent name shown in the receipt lines
        :param receipt_file: Open server_receipts.log, or None to log each receipt to the console
        :param client_process: Client process for the snapshot once all requests arrive, or None
        """
        count: int = 0
        use_dots: bool = receipt_file is not None
        while not stop_event.is_set() and count < expected_count:
            line: str = server_log_file.readline()
            if not line:
                stop_event.wait(0.5)
                continue
            if not primary_start_re.search(line):
                continue
            count += 1
            now_seconds: float = time.perf_counter()
            timestamp: str = time.strftime("%H:%M:%S", time.localtime())
            delta_seconds: float = now_seconds - fire_time_seconds
            detail: str = (f"  [server] {agent_label} request {count}/{expected_count} received [{timestamp}]"
                           f" (+{delta_seconds:.1f}s)")
            if use_dots:
                receipt_file.write(detail + "\n")
                receipt_file.flush()
                _progress_logger.info(".")
            else:
                logger.info("%s", detail)
            if count >= expected_count:
                ServerLogMonitor._log_all_received(use_dots, count, expected_count, delta_seconds, client_process)

    @staticmethod
    def _log_all_received(use_dots: bool, count: int, expected_count: int, elapsed_seconds: float,
                          client_process: Optional[psutil.Process]) -> None:
        """
        Log the final receipt summary and client snapshot.

        :param use_dots: True when arrivals were shown as dots, so the dot line needs ending
        :param count: Number of arrivals seen
        :param expected_count: Number of arrivals waited for
        :param elapsed_seconds: Seconds from firing to the last arrival
        :param client_process: Client process for the snapshot, or None
        """
        if use_dots:
            _progress_logger.info("\n")
            logger.info("  All %s/%s requests received by server (%.1fs)", count, expected_count, elapsed_seconds)
        snapshot: Optional[Dict[str, Any]] = ResourceMonitor.snapshot(client_process)
        if snapshot:
            client_rss_megabytes: float = snapshot.get("rss_megabytes")
            client_cpu_percent: float = snapshot.get("cpu_percent")
            logger.info("  Client AFTER: RSS %.1fM, CPU %.1f%%", client_rss_megabytes, client_cpu_percent)
        ResourceMonitor.log_system_memory("RECEIVED")
