
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
from unittest import TestCase

from tests.load_tests.reporting.rebuild_results import ResultsRebuilder


# pylint: disable=protected-access
class TestRebuiltAggregates(TestCase):
    """
    Unit tests for the aggregates a rebuild writes.

    A rebuilt run is often the only surviving record of an interrupted
    run, so its headline numbers have to mean what they say.
    """

    def setUp(self):
        """Create a run directory removed again after each test."""
        self._dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self._dir)
        os.makedirs(os.path.join(self._dir, "requests"))

    def _build_run(self, elapsed_by_id) -> dict:
        """Rebuild a run of successful requests with the given timings."""
        lines = []
        for req_id, elapsed in elapsed_by_id.items():
            path = os.path.join(
                self._dir, "requests", f"request_{req_id}_stdout.txt",
            )
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(
                    '{"reservation_id": "abc-%s",'
                    ' "agent_network_name": "music_nerd"}\n' % req_id
                )
            lines.append(f"Request {req_id}: CREATED ({elapsed:.2f}s)\n")
        log_path = os.path.join(self._dir, "load_test.log")
        with open(log_path, "w", encoding="utf-8") as handle:
            handle.writelines(lines)

        ResultsRebuilder(self._dir).run()

        json_path = os.path.join(self._dir, "raw_results.json")
        with open(json_path, "r", encoding="utf-8") as handle:
            return json.load(handle)["aggregates"]

    def test_average_latency_is_the_mean_request_time(self):
        """Latency averages the requests, not the run.

        Requests overlap, so dividing the slowest request by the
        request count would shrink the average by the concurrency
        factor and make a slow run look fast.
        """
        aggregates = self._build_run({1: 30.0, 2: 30.0, 3: 30.0})

        self.assertEqual(aggregates["avg_latency_seconds"], 30.0)

    def test_average_latency_reflects_uneven_requests(self):
        """The mean is taken over every request's own elapsed time."""
        aggregates = self._build_run({1: 1.0, 2: 2.0, 3: 6.0})

        self.assertEqual(aggregates["avg_latency_seconds"], 3.0)

    def test_total_elapsed_is_the_slowest_request(self):
        """Total elapsed still stands in for the run's wall clock."""
        aggregates = self._build_run({1: 1.0, 2: 2.0, 3: 6.0})

        self.assertEqual(aggregates["total_elapsed_seconds"], 6.0)
