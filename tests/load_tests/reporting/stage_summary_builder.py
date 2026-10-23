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

import re
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from tests.load_tests.cost_estimator import CostEstimator


class StageSummaryBuilder:
    """
    Builds the summary dict of one load-test stage and adds server-log data to its request results.
    """

    @staticmethod
    # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals,too-many-branches
    def build_stage_summary(
            stage_num: int,
            round_num: int,
            actual_requests: int,
            counts: Dict[str, Any],
            elapsed: float,
            retries: Dict[str, int],
            total_retries: int,
            amplification: float,
            results: List[Dict[str, Any]],
            server_counts: Dict[str, Any],
            disconnections: List[Dict[str, str]],
            server_errors: List[Dict[str, str]],
            tool_warnings: List[Dict[str, str]],
            network_tokens: List[Dict[str, Any]],
            validation_events: List[Dict[str, Any]],
            has_server_log: bool,
            has_tokens: bool,
            monitor_resources: bool,
            before_server: Optional[Dict[str, Any]],
            after_server: Optional[Dict[str, Any]],
            peak_threads: Optional[int],
            peak_server_rss: Optional[float],
            before_client: Optional[Dict[str, Any]] = None,
            peak_client: Optional[Dict[str, Any]] = None,
            settled_client: Optional[Dict[str, Any]] = None,
            before_system_memory_percent: Optional[float] = None,
            after_system_memory_percent: Optional[float] = None,
            peak_system_memory: Optional[Dict[str, float]] = None,
            peak_system_cpu_percent: Optional[float] = None,
            before_sys: Optional[Dict[str, float]] = None,
            after_sys: Optional[Dict[str, float]] = None,
            peak_system_threads: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Assemble the stage summary dict.

        :param stage_num: Stage number
        :param round_num: Round number
        :param actual_requests: Number of requests sent in this stage
        :param counts: Request counts by status
        :param elapsed: Stage time in seconds
        :param retries: Retry counts by kind
        :param total_retries: Total number of retries
        :param amplification: Server requests per client request
        :param results: Request results of the stage
        :param server_counts: Request counts from the server log
        :param disconnections: Disconnections from the server log
        :param server_errors: Server errors from the server log
        :param tool_warnings: Tool warnings from the server log
        :param network_tokens: Token usage per agent network from the server log
        :param validation_events: Validation events from the server log
        :param has_server_log: True when the server log can be read
        :param has_tokens: True when token data is reported
        :param monitor_resources: True to add the server thread and RSS snapshots
        :param before_server: Server snapshot before the stage, or None
        :param after_server: Server snapshot after the stage, or None
        :param peak_threads: Peak server thread count, or None
        :param peak_server_rss: Peak server RSS, or None
        :param before_client: Client snapshot before the stage, or None
        :param peak_client: Peak client snapshot during the stage, or None
        :param settled_client: Client snapshot after the stage, or None
        :param before_system_memory_percent: System memory percent before the stage, or None
        :param after_system_memory_percent: System memory percent after the stage, or None
        :param peak_system_memory: Peak system memory snapshot, or None
        :param peak_system_cpu_percent: Peak system CPU percent, or None
        :param before_sys: System snapshot before the stage, or None
        :param after_sys: System snapshot after the stage, or None
        :param peak_system_threads: Peak system thread count, or None
        :return: A dictionary with "stage", "round", "concurrent", "counts", "elapsed", "retries", "total_retries",
            "amplification", "results", "primary_started", "primary_finished", "total_started", "total_finished",
            "disconnections", "server_errors", "tool_warnings", "network_tokens", "validation_events",
            "has_server_log" and "has_tokens", plus the "before_*", "after_*" and "peak_*" thread, RSS and system
            keys whose snapshot or value is given
        """
        summary_entry: Dict[str, Any] = {
            "stage": stage_num,
            "round": round_num,
            "concurrent": actual_requests,
            "counts": counts,
            "elapsed": elapsed,
            "retries": retries,
            "total_retries": total_retries,
            "amplification": amplification,
            "results": results,
            "primary_started": server_counts.get("primary_started"),
            "primary_finished": server_counts.get("primary_finished"),
            "total_started": server_counts.get("total_started"),
            "total_finished": server_counts.get("total_finished"),
            "disconnections": disconnections,
            "server_errors": server_errors,
            "tool_warnings": tool_warnings,
            "network_tokens": network_tokens,
            "validation_events": validation_events,
            "has_server_log": has_server_log,
            "has_tokens": has_tokens,
        }
        if monitor_resources:
            if before_server:
                summary_entry["before_threads"] = before_server.get("threads")
                summary_entry["before_server_rss"] = before_server.get("rss_megabytes")
            if after_server:
                summary_entry["after_threads"] = after_server.get("threads")
                summary_entry["after_server_rss"] = after_server.get("rss_megabytes")
        if peak_threads is not None:
            summary_entry["peak_threads"] = peak_threads
        if peak_server_rss is not None:
            summary_entry["peak_server_rss"] = peak_server_rss
        if before_client:
            summary_entry["before_client_rss"] = before_client.get("rss_megabytes")
        if settled_client:
            summary_entry["after_client_rss"] = settled_client.get("rss_megabytes")
        if peak_client:
            summary_entry["peak_client_rss"] = peak_client.get("rss_megabytes")
        if before_system_memory_percent is not None:
            summary_entry["before_sys_mem_pct"] = before_system_memory_percent
        if after_system_memory_percent is not None:
            summary_entry["after_sys_mem_pct"] = after_system_memory_percent
        if peak_system_memory is not None:
            summary_entry["peak_sys_mem_pct"] = peak_system_memory.get("memory_percent")
            summary_entry["peak_sys_mem_avail_gb"] = peak_system_memory.get("available_gigabytes")
        if peak_system_cpu_percent is not None:
            summary_entry["peak_sys_cpu"] = peak_system_cpu_percent
        if before_sys:
            summary_entry["before_sys_mem_avail_gb"] = before_sys.get("mem_avail_gb")
            summary_entry["before_sys_cpu"] = before_sys.get("cpu_pct")
            summary_entry["before_sys_threads"] = before_sys.get("threads")
        if after_sys:
            summary_entry["after_sys_mem_avail_gb"] = after_sys.get("mem_avail_gb")
            summary_entry["after_sys_cpu"] = after_sys.get("cpu_pct")
            summary_entry["after_sys_threads"] = after_sys.get("threads")
        if peak_system_threads is not None:
            summary_entry["peak_sys_threads"] = peak_system_threads
        return summary_entry

    @staticmethod
    def attach_token_data(results: List[Dict[str, Any]], token_data: Dict[str, Dict[str, Any]]) -> None:
        """
        Attach token accounting data to request results.

        The server assigns its own request_id numbering (e.g. request-3,
        request-4) which differs from the client's (request-1, request-2).
        Match by order: sort server entries by request_id number, then
        attach to client results in submission order.

        :param results: Request results, updated in place
        :param token_data: Token accounting entries from the server log, by server request_id
        """
        if not token_data:
            return

        token_entries: List[Dict[str, Any]] = list(token_data.values())
        sorted_entries: List[Dict[str, Any]] = sorted(token_entries, key=StageSummaryBuilder._request_id_sort_key)
        sorted_results: List[Dict[str, Any]] = sorted(results, key=StageSummaryBuilder._request_id_sort_key)

        result: Dict[str, Any]
        entry: Dict[str, Any]
        # Copy each entry's token counts to the result in the same sorted place.
        for result, entry in zip(sorted_results, sorted_entries):
            prompt_tokens: int = entry.get("prompt_tokens", 0)
            completion_tokens: int = entry.get("completion_tokens", 0)
            model: str = entry.get("model", "unknown")
            cost_usd: float = CostEstimator.estimate(prompt_tokens, completion_tokens, model)
            token_fields: Dict[str, Any] = {
                "total_tokens": entry.get("total_tokens"),
                "prompt_tokens": entry.get("prompt_tokens"),
                "completion_tokens": entry.get("completion_tokens"),
                "llm_calls": entry.get("llm_calls"),
                "model": entry.get("model"),
                "reporting_agent": entry.get("reporting_agent"),
                "server_request_id": entry.get("request_id"),
                "cost_usd": cost_usd,
            }
            result.update(token_fields)

    @staticmethod
    def enrich_failure_reasons(results: List[Dict[str, Any]], validation_events: List[Dict[str, Any]]) -> None:
        """
        Append validation fix cycle info to failure reasons.

        :param results: Request results, updated in place
        :param validation_events: Validation events from the server log
        """
        if not validation_events:
            return
        events_by_request_id: Dict[str, Dict[str, Any]] = {}
        validation_event: Dict[str, Any]
        # Index the validation events by request_id; a later event for the same request_id wins.
        for validation_event in validation_events:
            event_request_id: str = validation_event.get("request_id")
            events_by_request_id[event_request_id] = validation_event
        result: Dict[str, Any]
        # Add the fix cycles of each result's validation event to its failure reason.
        for result in results:
            request_id: str = result.get("request_id", "")
            event: Optional[Dict[str, Any]] = events_by_request_id.get(request_id)
            if event is None:
                continue
            fix_cycles: int = event.get("fix_cycles", 0)
            if fix_cycles <= 0:
                continue
            existing: str = result.get("failure_reason") or ""
            suffix: str = f" ({fix_cycles} validation fix cycle(s))"
            result["failure_reason"] = existing + suffix

    @staticmethod
    def _request_id_sort_key(item: Dict[str, Any]) -> int:
        """
        Sort key for a result or token entry by the number at the end of its request_id.

        :param item: Request result or token entry with a "request_id" key
        :return: The number at the end of the request_id, or 0 when it has none
        """
        request_id: str = item.get("request_id", "")
        return StageSummaryBuilder._token_sort_key(request_id)

    @staticmethod
    def _token_sort_key(request_id: str) -> int:
        """
        Extract the numeric suffix from a request_id for sorting.

        :param request_id: Request id such as "request-3"
        :return: The number at the end of request_id, or 0 when it has none
        """
        match: Optional[re.Match] = re.search(r"(\d+)$", request_id)
        if match is None:
            return 0
        digits: str = match.group(1)
        return int(digits)
