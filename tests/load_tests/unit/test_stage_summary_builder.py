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

from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from unittest import TestCase

from tests.load_tests.reporting.stage_summary_builder import StageSummaryBuilder


class TestStageSummaryBuilder(TestCase):
    """
    Tests for StageSummaryBuilder.
    """

    @staticmethod
    def _build_summary(snapshot_values: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build a stage summary with fixed stage fields and the given snapshots.

        :param snapshot_values: A dict with the following keys; a missing snapshot is None:
            "monitor_resources"   True to add the server thread and RSS snapshots
            "before_server"       Server snapshot before the stage
            "after_server"        Server snapshot after the stage
            "before_client"       Client snapshot before the stage
            "peak_system_memory"  Peak system memory
            "after_sys"           System snapshot after the stage
        :return: The stage summary dict from build_stage_summary()
        """
        monitor_resources: bool = snapshot_values.get("monitor_resources")
        before_server: Optional[Dict[str, Any]] = snapshot_values.get("before_server")
        after_server: Optional[Dict[str, Any]] = snapshot_values.get("after_server")
        before_client: Optional[Dict[str, Any]] = snapshot_values.get("before_client")
        peak_system_memory: Optional[Dict[str, float]] = snapshot_values.get("peak_system_memory")
        after_sys: Optional[Dict[str, float]] = snapshot_values.get("after_sys")
        summary_inputs: Dict[str, Any] = {
            "stage_num": 1,
            "round_num": 2,
            "actual_requests": 3,
            "counts": {"ok": 3},
            "total_time_seconds": 1.5,
            "retries": {},
            "total_retries": 0,
            "amplification": 1.0,
            "results": [],
            "server_counts": {"primary_started": 3, "primary_finished": 3},
            "disconnections": [],
            "server_errors": [],
            "tool_warnings": [],
            "network_tokens": [],
            "validation_events": [],
            "has_server_log": True,
            "has_tokens": False,
            "monitor_resources": monitor_resources,
            "before_server": before_server,
            "after_server": after_server,
            "peak_server_threads": None,
            "peak_server_rss_megabytes": None,
            "before_client": before_client,
            "peak_system_memory": peak_system_memory,
            "after_system": after_sys,
        }
        summary_builder: StageSummaryBuilder = StageSummaryBuilder(summary_inputs)
        summary: Dict[str, Any] = summary_builder.build_stage_summary()
        return summary

    def test_attach_token_data_matches_by_request_number(self) -> None:
        """
        Server entries sorted by request number go to client results sorted the same way.
        """
        results: List[Dict[str, Any]] = [{"request_id": "request-2"}, {"request_id": "request-1"}]
        token_data: Dict[str, Dict[str, Any]] = {
            "request-11": {"request_id": "request-11", "total_tokens": 20, "model": "gpt-4o"},
            "request-10": {"request_id": "request-10", "total_tokens": 10, "model": "gpt-4o"},
        }
        StageSummaryBuilder.attach_token_data(results, token_data)
        self.assertEqual(results[1].get("server_request_id"), "request-10")
        self.assertEqual(results[1].get("total_tokens"), 10)
        self.assertEqual(results[0].get("server_request_id"), "request-11")
        self.assertEqual(results[0].get("total_tokens"), 20)
        self.assertIn("cost_usd", results[0])

    def test_attach_token_data_without_data(self) -> None:
        """
        No token data leaves the results as they are.
        """
        results: List[Dict[str, Any]] = [{"request_id": "request-1"}]
        StageSummaryBuilder.attach_token_data(results, {})
        self.assertEqual(results, [{"request_id": "request-1"}])

    def test_enrich_failure_reasons_adds_fix_cycles(self) -> None:
        """
        A result with fix cycles gets them added to its failure reason; others stay the same.
        """
        results: List[Dict[str, Any]] = [
            {"request_id": "request-1", "failure_reason": "bad output"},
            {"request_id": "request-2"},
            {"request_id": "request-3", "failure_reason": "timeout"},
        ]
        validation_events: List[Dict[str, Any]] = [
            {"request_id": "request-1", "fix_cycles": 2},
            {"request_id": "request-2", "fix_cycles": 1},
            {"request_id": "request-3", "fix_cycles": 0},
        ]
        StageSummaryBuilder.enrich_failure_reasons(results, validation_events)
        self.assertEqual(results[0].get("failure_reason"), "bad output (2 validation fix cycle(s))")
        self.assertEqual(results[1].get("failure_reason"), " (1 validation fix cycle(s))")
        self.assertEqual(results[2].get("failure_reason"), "timeout")

    def test_build_stage_summary_without_snapshots(self) -> None:
        """
        Without snapshots the summary has only the stage fields and no resource keys.
        """
        summary: Dict[str, Any] = TestStageSummaryBuilder._build_summary({"monitor_resources": False})
        self.assertEqual(summary.get("stage"), 1)
        self.assertEqual(summary.get("round"), 2)
        self.assertEqual(summary.get("concurrent"), 3)
        self.assertEqual(summary.get("primary_started"), 3)
        self.assertIsNone(summary.get("total_started"))
        self.assertNotIn("before_threads", summary)
        self.assertNotIn("peak_sys_threads", summary)

    def test_build_stage_summary_with_snapshots(self) -> None:
        """
        Server snapshots count only with monitor_resources; client and system snapshots always count.
        """
        summary: Dict[str, Any] = TestStageSummaryBuilder._build_summary({
            "monitor_resources": True,
            "before_server": {"threads": 10, "rss_megabytes": 100.0},
            "after_server": {"threads": 12, "rss_megabytes": 120.0},
            "before_client": {"rss_megabytes": 50.0},
            "peak_system_memory": {"memory_percent": 40.0, "available_gigabytes": 8.0},
            "after_sys": {"available_gigabytes": 7.5, "cpu_percent": 20.0, "threads": 300},
        })
        self.assertEqual(summary.get("before_threads"), 10)
        self.assertEqual(summary.get("after_server_rss"), 120.0)
        self.assertEqual(summary.get("before_client_rss"), 50.0)
        self.assertEqual(summary.get("peak_sys_mem_avail_gb"), 8.0)
        self.assertEqual(summary.get("after_sys_threads"), 300)
        self.assertNotIn("peak_client_rss", summary)

    def test_build_stage_summary_server_snapshots_need_monitor_resources(self) -> None:
        """
        Server snapshots are left out when monitor_resources is False.
        """
        before_server: Dict[str, Any] = {"threads": 10, "rss_megabytes": 100.0}
        summary: Dict[str, Any] = TestStageSummaryBuilder._build_summary({
            "monitor_resources": False,
            "before_server": before_server,
        })
        self.assertNotIn("before_threads", summary)
        self.assertNotIn("before_server_rss", summary)
