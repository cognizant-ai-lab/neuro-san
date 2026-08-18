
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
import os
import shutil
import tempfile
from argparse import Namespace
from types import SimpleNamespace
from unittest import TestCase

from tests.load_tests.config import STATUS_CREATED
from tests.load_tests.load_test_cli import LoadTestOrchestrator


# These tests call a deliberately-internal helper directly; suppress
# protected-access warnings file-wide.
# pylint: disable=protected-access
class TestExportRawJsonAggregates(TestCase):
    """
    Unit tests for the aggregates in raw_results.json.

    The same keys are written by a live run and by --rebuild, so they
    have to mean the same thing in both or a trend built from a mix of
    the two compares unlike numbers.
    """

    def setUp(self):
        """Create an output directory removed again after each test."""
        self._dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self._dir)

    def _orchestrator(self) -> LoadTestOrchestrator:
        """Build an orchestrator with only what the export reads."""
        orchestrator = LoadTestOrchestrator.__new__(LoadTestOrchestrator)
        orchestrator._output_dir = self._dir
        orchestrator._server_ns_version = "0.6.92"
        orchestrator.server_log = None
        orchestrator.profile = SimpleNamespace(
            estimated_tokens_per_request=1000,
        )
        orchestrator.resource_reporter = SimpleNamespace(
            resource_rows=[], client_rows=[],
        )
        orchestrator.args = Namespace(
            agent="music_nerd", profile_path=None, level="norm",
            ramp=False, host="localhost", port=30011,
            request_timeout=120, idle_timeout=60, stage_timeout=300,
            total_timeout=600, settle_time=5, max_workers=10,
            num_rounds=1, num_requests=3, same_prompt=False,
            chat_filter=None,
        )
        return orchestrator

    def _export(self, elapsed_values) -> dict:
        """Export one stage of successful requests and read it back."""
        results = [
            {
                "request_id": f"request-{index}",
                "status": STATUS_CREATED,
                "elapsed": elapsed,
            }
            for index, elapsed in enumerate(elapsed_values, start=1)
        ]
        # One stage whose wall-clock time is the slowest request,
        # because the requests ran concurrently.
        stage_summaries = [{
            "concurrent": len(results),
            "results": results,
            "elapsed": max(elapsed_values),
        }]

        self._orchestrator()._export_raw_json(
            stage_summaries, exit_code=0,
        )

        path = os.path.join(self._dir, "raw_results.json")
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)["aggregates"]

    def test_average_latency_is_the_mean_request_time(self):
        """Concurrency must not divide the reported latency.

        Ten overlapping 30-second requests average 30 seconds, not the
        3 seconds that dividing wall-clock time by the request count
        would suggest.
        """
        aggregates = self._export([30.0] * 10)

        self.assertEqual(aggregates["avg_latency_seconds"], 30.0)

    def test_average_latency_reflects_uneven_requests(self):
        """The mean is taken over every request's own elapsed time."""
        aggregates = self._export([1.0, 2.0, 6.0])

        self.assertEqual(aggregates["avg_latency_seconds"], 3.0)

    def test_wall_clock_total_is_reported_separately(self):
        """Throughput is still derivable from the elapsed total."""
        aggregates = self._export([1.0, 2.0, 6.0])

        self.assertEqual(aggregates["total_elapsed_seconds"], 6.0)
        self.assertEqual(aggregates["total_requests"], 3)
