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

import logging
import os
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import TextIO

logger: logging.Logger = logging.getLogger(__name__)


class TokenLogWriter:
    """
    Reports token usage for a load-test run: totals on the console and
    per-request, per-agent detail in server_tokens.log.
    """

    @staticmethod
    def log_token_summary(results: List[Dict[str, Any]], output_dir: Optional[str] = None,
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
        for result in results:
            if result.get("total_tokens"):
                has_tokens = True
                break
        if not has_tokens:
            return
        if output_dir:
            TokenLogWriter._write_token_file(
                results, output_dir,
                network_tokens=network_tokens,
                validation_events=validation_events,
            )
            TokenLogWriter._log_token_totals(results)
        else:
            TokenLogWriter._log_token_per_request(results)

    @staticmethod
    def _log_token_per_request(results: List[Dict[str, Any]]) -> None:
        """
        Log per-request token lines to the console.

        :param results: Results of every request in the run
        """
        for result in results:
            total_tokens: int = result.get("total_tokens", 0)
            if not total_tokens:
                continue
            prompt_tokens: int = result.get("prompt_tokens", 0)
            completion_tokens: int = result.get("completion_tokens", 0)
            llm_calls: int = result.get("llm_calls", 0)
            model: str = result.get("model", "unknown")
            request_id: str = result.get("request_id", "?")
            logger.info(
                "  %s: %s tokens (%s prompt + %s completion), "
                "%s LLM call(s), model=%s",
                request_id, f"{total_tokens:,}",
                f"{prompt_tokens:,}",
                f"{completion_tokens:,}",
                llm_calls, model,
            )

    @staticmethod
    def _write_token_file(results: List[Dict[str, Any]], output_dir: str,
                          network_tokens: Optional[List[Dict[str, Any]]] = None,
                          validation_events: Optional[List[Dict[str, Any]]] = None) -> None:
        """
        Write per-request token detail to server_tokens.log.

        :param results: Results of every request in the run
        :param output_dir: Directory for server_tokens.log
        :param network_tokens: Per-agent token entries parsed from the server log
        :param validation_events: Validation retry events parsed from the server log
        """
        by_request: Dict[str, List[Dict[str, Any]]] = TokenLogWriter._group_network_tokens(
            network_tokens,
        )
        by_validation: Dict[str, Dict[str, Any]] = TokenLogWriter._group_validation_events(
            validation_events,
        )
        path: str = os.path.join(output_dir, "server_tokens.log")
        with open(path, "w", encoding="utf-8") as file_handle:
            for result in results:
                total_tokens: int = result.get("total_tokens", 0)
                if not total_tokens:
                    continue
                TokenLogWriter._write_token_request(
                    file_handle, result, by_request,
                    by_validation,
                )
        logger.info("  Detail:  %s", path)

    @staticmethod
    def _group_network_tokens(network_tokens: Optional[List[Dict[str, Any]]]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Group network token entries by request_id.

        :param network_tokens: Per-agent token entries parsed from the server log
        :return: request_id -> its token entries
        """
        by_request: Dict[str, List[Dict[str, Any]]] = {}
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
        for event in (validation_events or []):
            request_id: str = event.get("request_id", "")
            by_request[request_id] = event
        return by_request

    @staticmethod
    def _write_token_request(file_handle: TextIO, result: Dict[str, Any], by_request: Dict[str, List[Dict[str, Any]]],
                             by_validation: Dict[str, Dict[str, Any]]) -> None:
        """
        Write one request's token line with agent breakdown.

        :param file_handle: Open server_tokens.log
        :param result: The request's result
        :param by_request: request_id -> per-agent token entries
        :param by_validation: request_id -> validation event
        """
        request_id: str = result.get("request_id", "?")
        total_tokens: int = result.get("total_tokens", 0)
        llm_calls: int = result.get("llm_calls", 0)
        model: str = result.get("model", "unknown")
        agent: str = result.get("reporting_agent", "")
        elapsed_seconds: float = result.get("elapsed", 0)
        status: str = result.get("status", "?")
        agent_suffix: str = ""
        if agent:
            agent_suffix = f", agent={agent}"
        file_handle.write(
            f"{request_id}: {total_tokens:,} tokens, "
            f"{llm_calls} LLM call(s), "
            f"model={model}{agent_suffix}"
            f"  [{elapsed_seconds:.1f}s {status}]\n"
        )
        TokenLogWriter._write_validation_detail(
            file_handle, request_id, by_validation,
        )
        server_request_id: str = result.get("server_request_id", request_id)
        agents: List[Dict[str, Any]] = (
            by_request.get(server_request_id)
            or by_request.get(request_id)
            or []
        )
        if not agents and agent:
            file_handle.write(
                f"  {agent}: {llm_calls} call(s)"
                f"  {total_tokens:,} tokens"
                f" ({result.get('prompt_tokens', 0):,} prompt"
                f" / {result.get('completion_tokens', 0):,}"
                f" completion)\n"
            )
        elif not agents and not agent:
            file_handle.write(
                "  (agent data not found in server log)\n"
            )
        TokenLogWriter._write_agent_breakdown(file_handle, agents)
        if agents or agent or request_id in by_validation.keys():
            file_handle.write("\n")

    @staticmethod
    def _write_agent_breakdown(file_handle: TextIO, agents: List[Dict[str, Any]]) -> None:
        """
        Write one token line per agent of a request.

        :param file_handle: Open server_tokens.log
        :param agents: Per-agent token entries of the request
        """
        for agent_entry in agents:
            network_name: str = agent_entry.get("network", "?")
            agent_calls: int = agent_entry.get("llm_calls", 0)
            agent_total_tokens: int = agent_entry.get("total_tokens", 0)
            agent_prompt_tokens: int = agent_entry.get("prompt_tokens", 0)
            agent_completion_tokens: int = agent_entry.get("completion_tokens", 0)
            file_handle.write(
                f"  {network_name}: {agent_calls} call(s)"
                f"  {agent_total_tokens:,} tokens"
                f" ({agent_prompt_tokens:,} prompt"
                f" / {agent_completion_tokens:,} completion)\n"
            )

    @staticmethod
    def _write_validation_detail(file_handle: TextIO, request_id: str,
                                 by_validation: Dict[str, Dict[str, Any]]) -> None:
        """
        Write per-request validation retry detail.

        :param file_handle: Open server_tokens.log
        :param request_id: request_id of the request being written
        :param by_validation: request_id -> validation event
        """
        event: Optional[Dict[str, Any]] = by_validation.get(request_id)
        if not event:
            return
        attempts: int = event.get("attempts", 0)
        fix_cycles: int = event.get("fix_cycles", 0)
        file_handle.write(
            f"  Validation: {attempts} attempt(s),"
            f" {fix_cycles} fix cycle(s)\n"
        )
        errors: List[str] = event.get("errors", [])
        for error in errors:
            file_handle.write(f"    - {error}\n")

    @staticmethod
    def _log_token_totals(results: List[Dict[str, Any]]) -> None:
        """
        Log aggregate token totals to the console.

        :param results: Results of every request in the run
        """
        total_tokens: int = 0
        total_prompt_tokens: int = 0
        total_completion_tokens: int = 0
        count: int = 0
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
        average_tokens: int = total_tokens // count
        logger.info(
            "  Total: %s tokens (%s prompt + %s completion)",
            f"{total_tokens:,}", f"{total_prompt_tokens:,}",
            f"{total_completion_tokens:,}",
        )
        logger.info(
            "  %s requests, avg %s tokens/request",
            count, f"{average_tokens:,}",
        )
