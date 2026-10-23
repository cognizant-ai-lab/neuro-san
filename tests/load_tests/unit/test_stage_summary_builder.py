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
    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def _build_summary(monitor_resources: bool, before_server: Optional[Dict[str, Any]],
                       after_server: Optional[Dict[str, Any]], before_client: Optional[Dict[str, Any]],
                       peak_system_memory: Optional[Dict[str, float]], after_sys: Optional[Dict[str, float]]
                       ) -> Dict[str, Any]:
        """
        Build a stage summary with fixed stage fields and the given snapshots.

        :param monitor_resources: True to add the server thread and RSS snapshots
        :param before_server: Server snapshot before the stage, or None
        :param after_server: Server snapshot after the stage, or None
        :param before_client: Client snapshot before the stage, or None
        :param peak_system_memory: Peak system memory snapshot, or None
        :param after_sys: System snapshot after the stage, or None
        :return: The stage summary dict from build_stage_summary()
        """
        summary: Dict[str, Any] = StageSummaryBuilder.build_stage_summary(
            stage_num=1,
            round_num=2,
            actual_requests=3,
            counts={"ok": 3},
            elapsed=1.5,
            retries={},
            total_retries=0,
            amplification=1.0,
            results=[],
            server_counts={"primary_started": 3, "primary_finished": 3},
            disconnections=[],
            server_errors=[],
            tool_warnings=[],
            network_tokens=[],
            validation_events=[],
            has_server_log=True,
            has_tokens=False,
            monitor_resources=monitor_resources,
            before_server=before_server,
            after_server=after_server,
            peak_threads=None,
            peak_server_rss=None,
            before_client=before_client,
            peak_system_memory=peak_system_memory,
            after_sys=after_sys,
        )
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
        summary: Dict[str, Any] = self._build_summary(False, None, None, None, None, None)
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
        summary: Dict[str, Any] = self._build_summary(
            True,
            {"threads": 10, "rss_megabytes": 100.0},
            {"threads": 12, "rss_megabytes": 120.0},
            {"rss_megabytes": 50.0},
            {"memory_percent": 40.0, "available_gigabytes": 8.0},
            {"mem_avail_gb": 7.5, "cpu_pct": 20.0, "threads": 300},
        )
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
        summary: Dict[str, Any] = self._build_summary(False, before_server, None, None, None, None)
        self.assertNotIn("before_threads", summary)
        self.assertNotIn("before_server_rss", summary)
