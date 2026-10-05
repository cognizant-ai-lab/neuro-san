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
            total: int = result.get("total_tokens", 0)
            if not total:
                continue
            prompt_tok: int = result.get("prompt_tokens", 0)
            comp_tok: int = result.get("completion_tokens", 0)
            llm_calls: int = result.get("llm_calls", 0)
            model: str = result.get("model", "unknown")
            rid: str = result.get("request_id", "?")
            logger.info(
                "  %s: %s tokens (%s prompt + %s completion), "
                "%s LLM call(s), model=%s",
                rid, f"{total:,}",
                f"{prompt_tok:,}",
                f"{comp_tok:,}",
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
        with open(path, "w", encoding="utf-8") as fh:
            for result in results:
                total: int = result.get("total_tokens", 0)
                if not total:
                    continue
                TokenLogWriter._write_token_request(
                    fh, result, by_request,
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
            rid: str = entry.get("request_id", "")
            by_request.setdefault(rid, []).append(entry)
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
            rid: str = event.get("request_id", "")
            by_request[rid] = event
        return by_request

    @staticmethod
    def _write_token_request(fh: TextIO, result: Dict[str, Any], by_request: Dict[str, List[Dict[str, Any]]],
                             by_validation: Dict[str, Dict[str, Any]]) -> None:
        """
        Write one request's token line with agent breakdown.

        :param fh: Open server_tokens.log
        :param result: The request's result
        :param by_request: request_id -> per-agent token entries
        :param by_validation: request_id -> validation event
        """
        rid: str = result.get("request_id", "?")
        total: int = result.get("total_tokens", 0)
        llm_calls: int = result.get("llm_calls", 0)
        model: str = result.get("model", "unknown")
        agent: str = result.get("reporting_agent", "")
        elapsed: float = result.get("elapsed", 0)
        status: str = result.get("status", "?")
        agent_suffix: str = ""
        if agent:
            agent_suffix = f", agent={agent}"
        fh.write(
            f"{rid}: {total:,} tokens, "
            f"{llm_calls} LLM call(s), "
            f"model={model}{agent_suffix}"
            f"  [{elapsed:.1f}s {status}]\n"
        )
        TokenLogWriter._write_validation_detail(
            fh, rid, by_validation,
        )
        server_rid: str = result.get("server_request_id", rid)
        agents: List[Dict[str, Any]] = (
            by_request.get(server_rid)
            or by_request.get(rid)
            or []
        )
        if not agents and agent:
            fh.write(
                f"  {agent}: {llm_calls} call(s)"
                f"  {total:,} tokens"
                f" ({result.get('prompt_tokens', 0):,} prompt"
                f" / {result.get('completion_tokens', 0):,}"
                f" completion)\n"
            )
        elif not agents and not agent:
            fh.write(
                "  (agent data not found in server log)\n"
            )
        TokenLogWriter._write_agent_breakdown(fh, agents)
        if agents or agent or rid in by_validation.keys():
            fh.write("\n")

    @staticmethod
    def _write_agent_breakdown(fh: TextIO, agents: List[Dict[str, Any]]) -> None:
        """
        Write one token line per agent of a request.

        :param fh: Open server_tokens.log
        :param agents: Per-agent token entries of the request
        """
        for ag_entry in agents:
            net: str = ag_entry.get("network", "?")
            a_calls: int = ag_entry.get("llm_calls", 0)
            a_total: int = ag_entry.get("total_tokens", 0)
            a_prompt: int = ag_entry.get("prompt_tokens", 0)
            a_comp: int = ag_entry.get("completion_tokens", 0)
            fh.write(
                f"  {net}: {a_calls} call(s)"
                f"  {a_total:,} tokens"
                f" ({a_prompt:,} prompt"
                f" / {a_comp:,} completion)\n"
            )

    @staticmethod
    def _write_validation_detail(fh: TextIO, rid: str, by_validation: Dict[str, Dict[str, Any]]) -> None:
        """
        Write per-request validation retry detail.

        :param fh: Open server_tokens.log
        :param rid: request_id of the request being written
        :param by_validation: request_id -> validation event
        """
        event: Optional[Dict[str, Any]] = by_validation.get(rid)
        if not event:
            return
        attempts: int = event.get("attempts", 0)
        fix_cycles: int = event.get("fix_cycles", 0)
        fh.write(
            f"  Validation: {attempts} attempt(s),"
            f" {fix_cycles} fix cycle(s)\n"
        )
        errors: List[str] = event.get("errors", [])
        for err in errors:
            fh.write(f"    - {err}\n")

    @staticmethod
    def _log_token_totals(results: List[Dict[str, Any]]) -> None:
        """
        Log aggregate token totals to the console.

        :param results: Results of every request in the run
        """
        total_tok: int = 0
        total_prompt: int = 0
        total_comp: int = 0
        count: int = 0
        for result in results:
            tok: int = result.get("total_tokens", 0)
            if not tok:
                continue
            total_tok += tok
            total_prompt += result.get("prompt_tokens", 0)
            total_comp += result.get("completion_tokens", 0)
            count += 1
        if count == 0:
            return
        avg: int = total_tok // count
        logger.info(
            "  Total: %s tokens (%s prompt + %s completion)",
            f"{total_tok:,}", f"{total_prompt:,}",
            f"{total_comp:,}",
        )
        logger.info(
            "  %s requests, avg %s tokens/request",
            count, f"{avg:,}",
        )
