
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
from typing import Any
from typing import Dict
from typing import List
from unittest import TestCase
from unittest.mock import patch

from tests.load_tests.load_test_constants import RAW_RESULTS_FILE_NAME
from tests.load_tests.load_test_constants import STATUS_CREATED
from tests.load_tests.load_test_cli import LoadTestCli
from tests.load_tests.prompts.agent_profile import AgentProfile
from tests.load_tests.reporting.resource_reporter import ResourceReporter
from tests.load_tests.validation.server_checker import ServerChecker


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

    def setUp(self) -> None:
        """
        Create an output directory removed again after each test.
        """
        self._dir: str = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self._dir)

    def _load_test_cli(self) -> LoadTestCli:
        """
        Build a LoadTestCli with only what the export reads.

        :return: LoadTestCli that writes to the scratch directory
        """
        load_test_cli: LoadTestCli = LoadTestCli.__new__(LoadTestCli)
        load_test_cli._output_dir = self._dir
        load_test_cli.server_log = None
        load_test_cli.hocon_files = []
        load_test_cli.profile = AgentProfile("hello_world", {"estimated_tokens_per_request": 1000})
        load_test_cli.resource_reporter = ResourceReporter()
        load_test_cli.args = Namespace(
            agent="music_nerd", profile_path=None, level="norm",
            ramp=False, host="localhost", port=30011,
            request_timeout=120, idle_timeout=60, stage_timeout=300,
            total_timeout=600, settle_time=5, max_workers=10,
            num_rounds=1, num_requests=3, same_prompt=False,
            allow_caching=False, chat_filter=None,
            fixtures_hocon_dir=None,
        )
        load_test_cli.server_checker = ServerChecker(load_test_cli.args)
        # The server version comes from /healthz; patch the fetch so the cached version is "0.6.92".
        with patch.object(ServerChecker, "fetch_server_version", return_value="0.6.92"):
            load_test_cli.server_checker.resolve_ns_version()
        return load_test_cli

    def _export(self, elapsed_values_seconds: List[float]) -> Dict[str, Any]:
        """
        Export one stage of successful requests and read it back.

        :param elapsed_values_seconds: Elapsed seconds, one per request
        :return: Aggregates read back from raw_results.json
        """
        results: List[Dict[str, Any]] = []
        index: int
        elapsed_seconds: float
        # One successful request per elapsed time, numbered from 1.
        for index, elapsed_seconds in enumerate(elapsed_values_seconds, start=1):
            results.append({"request_id": f"request-{index}", "status": STATUS_CREATED, "elapsed": elapsed_seconds})
        # One stage whose wall-clock time is the slowest request,
        # because the requests ran concurrently.
        stage_summaries: List[Dict[str, Any]] = [{
            "concurrent": len(results),
            "results": results,
            "elapsed": max(elapsed_values_seconds),
        }]

        self._load_test_cli()._export_raw_json(stage_summaries, exit_code=0)

        path: str = os.path.join(self._dir, RAW_RESULTS_FILE_NAME)
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle).get("aggregates", {})

    def test_average_latency_is_the_mean_request_time(self) -> None:
        """
        Concurrency must not divide the reported latency.

        Ten overlapping 30-second requests average 30 seconds, not the
        3 seconds that dividing wall-clock time by the request count
        would suggest.
        """
        aggregates: Dict[str, Any] = self._export([30.0] * 10)

        self.assertEqual(aggregates.get("avg_latency_seconds", 0.0), 30.0)

    def test_average_latency_reflects_uneven_requests(self) -> None:
        """
        The mean is taken over every request's own elapsed time.
        """
        aggregates: Dict[str, Any] = self._export([1.0, 2.0, 6.0])

        self.assertEqual(aggregates.get("avg_latency_seconds", 0.0), 3.0)

    def test_wall_clock_total_is_reported_separately(self) -> None:
        """
        Throughput is still derivable from the elapsed total.
        """
        aggregates: Dict[str, Any] = self._export([1.0, 2.0, 6.0])

        self.assertEqual(aggregates.get("total_elapsed_seconds", 0.0), 6.0)
        self.assertEqual(aggregates.get("total_requests", 0), 3)
