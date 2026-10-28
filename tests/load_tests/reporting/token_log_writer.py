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

from logging import Logger
from logging import getLogger
import os
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from tests.load_tests.load_test_constants import LoadTestConstants


class TokenLogWriter:
    """
    Reports token usage for a load-test run: totals on the console and
    per-request, per-agent detail in server_tokens.log.

    _write_token_file() opens server_tokens.log once and passes the open file to each _write_* method,
    which adds its own lines. The helpers stay static and take the open file, so the file is opened and closed
    in one with block in _write_token_file().
    """

    def __init__(self) -> None:
        """
        Constructor.
        """
        self.logger: Logger = getLogger(self.__class__.__name__)

    def log_token_summary(self, results: List[Dict[str, Any]], output_dir: Optional[str] = None,
                          network_tokens: Optional[List[Dict[str, Any]]] = None,
                          validation_events: Optional[List[Dict[str, Any]]] = None) -> None:
        """
        Log token usage summary to console, detail to file.

        When output_dir is provided, per-request lines go to
        server_tokens.log and only totals appear on the console.
        Without output_dir, per-request lines go to the console.

        :param results: Results of every request in the run
        :param output_dir: Directory for server_tokens.log, or None for console only
        :param network_tokens: Per-agent token entries parsed from the server log
        :param validation_events: Validation retry events parsed from the server log
        """
        has_tokens: bool = False
        result: Dict[str, Any]
        # Stop at the first result that has tokens.
        for result in results:
            if result.get("total_tokens"):
                has_tokens = True
                break
        if not has_tokens:
            return
        if output_dir:
            self._write_token_file(
                results, output_dir,
                network_tokens=network_tokens,
                validation_events=validation_events,
            )
            self._log_token_totals(results)
        else:
            self._log_token_per_request(results)

    def _log_token_per_request(self, results: List[Dict[str, Any]]) -> None:
        """
        Log per-request token lines to the console.

        :param results: Results of every request in the run
        """
        result: Dict[str, Any]
        # One log line per request that used tokens.
        for result in results:
            total_tokens: int = result.get("total_tokens", 0)
            if not total_tokens:
                continue
            prompt_tokens: int = result.get("prompt_tokens", 0)
            completion_tokens: int = result.get("completion_tokens", 0)
            llm_calls: int = result.get("llm_calls", 0)
            model: str = result.get("model", "unknown")
            request_id: str = result.get("request_id", "?")
            self.logger.info(
                "  %s: %s tokens (%s prompt + %s completion), %s LLM call(s), model=%s",
                request_id, f"{total_tokens:,}",
                f"{prompt_tokens:,}",
                f"{completion_tokens:,}",
                llm_calls, model,
            )

    def _write_token_file(self, results: List[Dict[str, Any]], output_dir: str,
                          network_tokens: Optional[List[Dict[str, Any]]] = None,
                          validation_events: Optional[List[Dict[str, Any]]] = None) -> None:
        """
        Write per-request token detail to server_tokens.log.

        :param results: Results of every request in the run
        :param output_dir: Directory for server_tokens.log
        :param network_tokens: Per-agent token entries parsed from the server log
        :param validation_events: Validation retry events parsed from the server log
        """
        by_request: Dict[str, List[Dict[str, Any]]] = TokenLogWriter._group_network_tokens(network_tokens)
        by_validation: Dict[str, Dict[str, Any]] = TokenLogWriter._group_validation_events(validation_events)
        path: str = os.path.join(output_dir, LoadTestConstants.SERVER_TOKENS_LOG_FILE_NAME)
        with open(path, "w", encoding="utf-8") as file_handle:
            result: Dict[str, Any]
            # One file section per request that used tokens.
            for result in results:
                total_tokens: int = result.get("total_tokens", 0)
                if not total_tokens:
                    continue
                request_text: str = TokenLogWriter._token_request_text(result, by_request, by_validation)
                file_handle.write(request_text)
        self.logger.info("  Detail:  %s", path)

    @staticmethod
    def _group_network_tokens(network_tokens: Optional[List[Dict[str, Any]]]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Group network token entries by request_id.

        :param network_tokens: Per-agent token entries parsed from the server log
        :return: request_id -> its token entries
        """
        by_request: Dict[str, List[Dict[str, Any]]] = {}
        entry: Dict[str, Any]
        # Group the token entries by request id.
        for entry in (network_tokens or []):
            request_id: str = entry.get("request_id", "")
            by_request.setdefault(request_id, []).append(entry)
        return by_request

    @staticmethod
    def _group_validation_events(validation_events: Optional[List[Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
        """
        Index validation events by request_id.

        :param validation_events: Validation retry events parsed from the server log
        :return: request_id -> its validation event
        """
        by_request: Dict[str, Dict[str, Any]] = {}
        event: Dict[str, Any]
        # Index the validation events by request id.
        for event in (validation_events or []):
            request_id: str = event.get("request_id", "")
            by_request[request_id] = event
        return by_request

    @staticmethod
    def _token_request_text(result: Dict[str, Any], by_request: Dict[str, List[Dict[str, Any]]],
                            by_validation: Dict[str, Dict[str, Any]]) -> str:
        """
        Build one request's server_tokens.log text: its token line, validation detail and agent breakdown.

        :param result: The request's result
        :param by_request: request_id -> per-agent token entries
        :param by_validation: request_id -> validation event
        :return: The request's lines, each ending in a newline
        """
        request_id: str = result.get("request_id", "?")
        agent: str = result.get("reporting_agent", "")
        request_line: str = TokenLogWriter._format_request_line(result)
        validation_text: str = TokenLogWriter._validation_detail_text(request_id, by_validation)
        text_parts: List[str] = [request_line, validation_text]
        server_request_id: str = result.get("server_request_id", request_id)
        agents: List[Dict[str, Any]] = by_request.get(server_request_id) or by_request.get(request_id) or []
        if not agents and agent:
            reporting_agent_text: str = TokenLogWriter._reporting_agent_text(result)
            text_parts.append(reporting_agent_text)
        elif not agents and not agent:
            text_parts.append("  (agent data not found in server log)\n")
        agent_text: str = TokenLogWriter._agent_breakdown_text(agents)
        text_parts.append(agent_text)
        if (agents
                or agent
                or request_id in by_validation.keys()):
            text_parts.append("\n")
        text: str = "".join(text_parts)
        return text

    @staticmethod
    def _reporting_agent_text(result: Dict[str, Any]) -> str:
        """
        Make the token line of a request whose agents the server log does not list, from the client's own counts.

        :param result: The request result
        :return: The line with the reporting agent, its LLM calls and its tokens
        """
        agent: str = result.get("reporting_agent", "")
        total_tokens: int = result.get("total_tokens", 0)
        prompt_tokens: int = result.get("prompt_tokens", 0)
        completion_tokens: int = result.get("completion_tokens", 0)
        llm_calls: int = result.get("llm_calls", 0)
        split_text: str = f"({prompt_tokens:,} prompt / {completion_tokens:,} completion)"
        reporting_agent_text: str = f"  {agent}: {llm_calls} call(s)  {total_tokens:,} tokens {split_text}\n"
        return reporting_agent_text

    @staticmethod
    def _format_request_line(result: Dict[str, Any]) -> str:
        """
        Build one request's first server_tokens.log line, read by CrossRunComparison.SERVER_TOKEN_RE.

        :param result: The request's result
        :return: The line, e.g. "request-1: 1,500 tokens (1,000 prompt + 500 completion), 12 LLM call(s),
            model=gpt-4o-mini, agent=hello_world  [1.2s CREATED]" plus a newline
        """
        request_id: str = result.get("request_id", "?")
        total_tokens: int = result.get("total_tokens", 0)
        prompt_tokens: int = result.get("prompt_tokens", 0)
        completion_tokens: int = result.get("completion_tokens", 0)
        llm_calls: int = result.get("llm_calls", 0)
        model: str = result.get("model", "unknown")
        agent: str = result.get("reporting_agent", "")
        elapsed_seconds: float = result.get("elapsed", 0)
        status: str = result.get("status", "?")
        agent_suffix: str = ""
        if agent:
            agent_suffix = f", agent={agent}"
        token_text: str = f"{total_tokens:,} tokens ({prompt_tokens:,} prompt + {completion_tokens:,} completion)"
        call_text: str = f"{llm_calls} LLM call(s), model={model}{agent_suffix}"
        timing_text: str = f"[{elapsed_seconds:.1f}s {status}]"
        return f"{request_id}: {token_text}, {call_text}  {timing_text}\n"

    @staticmethod
    def _agent_breakdown_text(agents: List[Dict[str, Any]]) -> str:
        """
        Build one token line per agent of a request.

        :param agents: Per-agent token entries of the request
        :return: The agent lines, each ending in a newline, or "" when there are no agents
        """
        text_parts: List[str] = []
        agent_entry: Dict[str, Any]
        # One line per agent of the request.
        for agent_entry in agents:
            network_name: str = agent_entry.get("network", "?")
            agent_calls: int = agent_entry.get("llm_calls", 0)
            agent_total_tokens: int = agent_entry.get("total_tokens", 0)
            agent_prompt_tokens: int = agent_entry.get("prompt_tokens", 0)
            agent_completion_tokens: int = agent_entry.get("completion_tokens", 0)
            split_text: str = f"({agent_prompt_tokens:,} prompt / {agent_completion_tokens:,} completion)"
            text_parts.append(f"  {network_name}: {agent_calls} call(s)  {agent_total_tokens:,} tokens {split_text}\n")
        text: str = "".join(text_parts)
        return text

    @staticmethod
    def _validation_detail_text(request_id: str, by_validation: Dict[str, Dict[str, Any]]) -> str:
        """
        Build one request's validation retry detail.

        :param request_id: request_id of the request being written
        :param by_validation: request_id -> validation event
        :return: The validation lines, each ending in a newline, or "" when the request has no validation event
        """
        event: Optional[Dict[str, Any]] = by_validation.get(request_id)
        if not event:
            return ""
        attempts: int = event.get("attempts", 0)
        fix_cycles: int = event.get("fix_cycles", 0)
        text_parts: List[str] = [f"  Validation: {attempts} attempt(s), {fix_cycles} fix cycle(s)\n"]
        errors: List[str] = event.get("errors", [])
        error: str
        # One line per validation error.
        for error in errors:
            text_parts.append(f"    - {error}\n")
        text: str = "".join(text_parts)
        return text

    def _log_token_totals(self, results: List[Dict[str, Any]]) -> None:
        """
        Log aggregate token totals to the console.

        :param results: Results of every request in the run
        """
        total_tokens: int = 0
        total_prompt_tokens: int = 0
        total_completion_tokens: int = 0
        count: int = 0
        result: Dict[str, Any]
        # Add up the tokens of each request that reported any.
        for result in results:
            token_count: int = result.get("total_tokens", 0)
            if not token_count:
                continue
            total_tokens += token_count
            total_prompt_tokens += result.get("prompt_tokens", 0)
            total_completion_tokens += result.get("completion_tokens", 0)
            count += 1
        if count == 0:
            return
        # Whole tokens per request, rounded down, e.g. 1001 / 2 -> 500.
        average_tokens: int = int(total_tokens / count)
        self.logger.info(
            "  Total: %s tokens (%s prompt + %s completion)",
            f"{total_tokens:,}", f"{total_prompt_tokens:,}",
            f"{total_completion_tokens:,}",
        )
        self.logger.info("  %s requests, avg %s tokens/request", count, f"{average_tokens:,}")
