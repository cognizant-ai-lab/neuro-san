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
from datetime import datetime
from json import JSONDecodeError
from json import loads
from logging import Logger
from logging import getLogger
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from tests.load_tests.load_test_constants import LoadTestConstants


class ServerLogParser:
    """
    Helpers that ServerLogMonitor uses to read records out of server log lines: regex matches, JSON lines
    and disconnections.

    Each helper works on lines or text already read from the log, so it holds no state.
    """

    def __init__(self) -> None:
        """
        Set up the logger of the parser.
        """
        self.logger: Logger = getLogger(self.__class__.__name__)

    def int_group(self, match: Optional[re.Match]) -> int:
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

    def extract_token_entry(self, block: str) -> Optional[Dict[str, Any]]:
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
        total_tokens: int = self.int_group(total_match)
        prompt_tokens: int = self.int_group(prompt_match)
        completion_tokens: int = self.int_group(completion_match)
        llm_calls: int = self.int_group(llm_calls_match)
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

    def collect_reporting_blocks(self, lines: List[str]) -> List[Dict[str, object]]:
        """
        Collect Request reporting blocks with their line positions.

        :param lines: Server log lines
        :return: One dict per Request reporting block, with "text" (its lines joined) and "end_index"
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
                    block_text: str = "".join(block_lines)
                    blocks.append({
                        "text": block_text,
                        "end_index": index,
                    })
                    in_block = False
                    block_lines = []
        return blocks

    def resolve_network_names(self, blocks: List[Dict[str, object]], lines: List[str]) -> List[Dict[str, Any]]:
        """
        Match each block to its network via Done-with log lines.

        :param blocks: Blocks from collect_reporting_blocks()
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
            entry: Optional[Dict[str, Any]] = self.extract_token_entry(block_text)
            if not entry:
                continue
            end_index: int = block.get("end_index", 0)
            network: Optional[str] = self.find_network_after(lines, end_index)
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

    def find_network_after(self, lines: List[str], end_index: int,
                           lookahead_lines: int = LoadTestConstants.NETWORK_LOOKAHEAD_LINES) -> Optional[str]:
        """
        Find the network name from Done-with lines after a block.

        :param lines: Server log lines
        :param end_index: Index of the last line of the block
        :param lookahead_lines: The search stops before line end_index + lookahead_lines, so it checks
                                lookahead_lines - 1 lines after the block
        :return: The network name, or None when no Done-with line is found
        """
        line_count: int = len(lines)
        limit: int = min(end_index + lookahead_lines, line_count)
        index: int
        # Look for a Done-with line in the lines after the block.
        for index in range(end_index + 1, limit):
            match: Optional[re.Match] = LoadTestConstants.DONE_STREAMING_PATTERN.search(lines[index])
            if match:
                return match.group(1)
        return None

    def collect_validation_events(self, lines: List[str]) -> List[Dict[str, Any]]:
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
            request_id_match: Optional[re.Match] = LoadTestConstants.REQUEST_ID_PATTERN.search(line)
            if not request_id_match:
                continue
            request_id = request_id_match.group(1)
            # pylint: disable=consider-iterating-dictionary
            if request_id not in by_request.keys():
                by_request[request_id] = {
                    "attempts": 0,
                    "fix_cycles": 0,
                    "errors": [],
                }
            entry: Dict[str, object] = by_request.get(request_id)
            if LoadTestConstants.VALIDATION_ATTEMPT_PATTERN.search(line):
                entry["attempts"] = entry.get("attempts", 0) + 1
            if LoadTestConstants.VALIDATION_REINVOKE_PATTERN.search(line):
                entry["fix_cycles"] = entry.get("fix_cycles", 0) + 1
            error_match: Optional[re.Match] = LoadTestConstants.VALIDATION_ERROR_PATTERN.search(line)
            if error_match:
                error_list_text: str = error_match.group(1)
                validation_errors: List[str] = self.parse_validation_errors(error_list_text)
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

    def parse_validation_errors(self, error_list_text: str) -> List[str]:
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
        for single_quoted, double_quoted in LoadTestConstants.VALIDATION_ERROR_ITEM_PATTERN.findall(error_list_text):
            errors.append(single_quoted or double_quoted)
        if not errors and error_list_text != "[]":
            self.logger.info("Could not find a quoted error in the validation errors %s", error_list_text)
            errors.append(error_list_text)
        return errors

    def match_streaming_chat_pairs(self, lines: List[str]) -> List[Dict[str, object]]:
        """
        Match Start/Finish pairs from server log lines.

        :param lines: Server log lines
        :return: One dict per Start/Finish pair, with "agent", "start_ts", "finish_ts", "duration_seconds"
            and "request_id"
        """
        # Start times keyed by "<agent> <request_id>": neither part holds a space.
        starts: Dict[str, float] = {}
        results: List[Dict[str, object]] = []
        line: str
        # Pair each streaming_chat Start record with its Finish record.
        for line in lines:
            entry: Any = None
            try:
                stripped_line: str = line.strip()
                entry = loads(stripped_line)
            except (JSONDecodeError, ValueError):
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
            agent: str = ""
            pair_key: str = ""
            if message.startswith("Start ") and "/streaming_chat" in message:
                agent = self._streaming_chat_agent(message, "Start ")
                pair_key = f"{agent} {request_id}"
                starts[pair_key] = timestamp_seconds
            elif message.startswith("Finish ") and "/streaming_chat" in message:
                agent = self._streaming_chat_agent(message, "Finish ")
                pair_key = f"{agent} {request_id}"
                start_seconds: Optional[float] = starts.pop(pair_key, None)
                if start_seconds is not None:
                    results.append({
                        "agent": agent,
                        "start_ts": start_seconds,
                        "finish_ts": timestamp_seconds,
                        "duration_seconds": timestamp_seconds - start_seconds,
                        "request_id": request_id,
                    })
        return results

    def disconnection_list(self, disconnections: Dict[str, Dict[str, str]]) -> List[Dict[str, str]]:
        """
        List the disconnections in first-seen order.

        :param disconnections: The disconnections by request id
        :return: The disconnection dicts, in first-seen order, each with "request_id" and "agent"
        """
        disconnection_list: List[Dict[str, str]] = []
        disconnection: Dict[str, str]
        # Keep the disconnections in first-seen order.
        for disconnection in disconnections.values():
            disconnection_list.append(disconnection)
        return disconnection_list

    def set_cancelled_agent(self, cancel_match: re.Match, disconnections: Dict[str, Dict[str, str]],
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

    def map_to_client_requests(self, disconnections: Dict[str, Dict[str, str]], primary_request_ids: List[str]) -> None:
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
            primary_number: int = self.request_number(primary_request_id)
            primary_numbers.append(primary_number)

        disconnection: Dict[str, str]
        # Find the client request that each disconnection belongs to.
        for disconnection in disconnections.values():
            request_id: str = disconnection.get("request_id", "")
            request_number: int = self.request_number(request_id)
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

    def request_number(self, request_id: str) -> int:
        """
        Read the number at the end of a server request_id, used to put request_ids in order.

        :param request_id: Server request_id
        :return: The number at the end of request_id, or -1 when there is none
        """
        match: Optional[re.Match] = re.search(r"(\d+)$", request_id)
        if match:
            return int(match.group(1))
        return -1

    def _streaming_chat_agent(self, message: str, prefix: str) -> str:
        """
        Get the agent name from a streaming_chat Start or Finish message.

        :param message: The log message, e.g. "Start hello_world/streaming_chat"
        :param prefix: "Start " or "Finish "
        :return: The agent name, e.g. "hello_world"
        """
        agent_path: str = message.replace(prefix, "")
        agent: str = agent_path.replace("/streaming_chat", "")
        return agent
