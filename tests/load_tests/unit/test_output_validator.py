
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
from unittest import TestCase

from tests.load_tests.load_test_constants import LoadTestConstants
from tests.load_tests.validation.output_validator import OutputValidator


class TestOutputValidator(TestCase):
    """
    Unit tests for OutputValidator.count_results() and log_stage_results().

    These counts drive the run's verdict and the numbers in
    raw_results.json, so a request must never vanish between the
    result list and the totals.
    """

    def test_each_status_is_counted(self) -> None:
        """
        Every known status lands in its own bucket.
        """
        counts: Dict[str, Any] = OutputValidator.count_results([
            {"status": LoadTestConstants.STATUS_CREATED},
            {"status": LoadTestConstants.STATUS_CREATED},
            {"status": LoadTestConstants.STATUS_FAILED},
            {"status": LoadTestConstants.STATUS_TIMEOUT},
            {"status": LoadTestConstants.STATUS_KILLED},
        ])

        self.assertEqual(counts.get(LoadTestConstants.STATUS_CREATED), 2)
        self.assertEqual(counts.get(LoadTestConstants.STATUS_FAILED), 1)
        self.assertEqual(counts.get(LoadTestConstants.STATUS_TIMEOUT), 1)
        self.assertEqual(counts.get(LoadTestConstants.STATUS_KILLED), 1)

    def test_no_results_counts_zero_not_empty(self) -> None:
        """
        An aborted stage still reports every bucket, all zero.
        """
        counts: Dict[str, Any] = OutputValidator.count_results([])

        expected_counts: Dict[str, int] = {
            LoadTestConstants.STATUS_CREATED: 0,
            LoadTestConstants.STATUS_FAILED: 0,
            LoadTestConstants.STATUS_TIMEOUT: 0,
            LoadTestConstants.STATUS_KILLED: 0,
        }
        self.assertEqual(counts, expected_counts)

    def test_unknown_status_counts_as_failed(self) -> None:
        """
        An unrecognized status is a failure, never a success.

        Counting it anywhere else -- or dropping it -- would let a
        run's totals disagree with the number of requests fired.
        """
        counts: Dict[str, Any] = OutputValidator.count_results([{"status": "WEIRD"}])

        self.assertEqual(counts.get(LoadTestConstants.STATUS_FAILED), 1)
        self.assertEqual(counts.get(LoadTestConstants.STATUS_CREATED), 0)

    def test_missing_status_counts_as_failed(self) -> None:
        """
        A result with no status recorded is treated as a failure.
        """
        counts: Dict[str, Any] = OutputValidator.count_results([{}])

        self.assertEqual(counts.get(LoadTestConstants.STATUS_FAILED), 1)

    def test_totals_match_the_number_of_results(self) -> None:
        """
        No request is lost or double-counted, whatever its status.
        """
        results: List[Dict[str, Any]] = [
            {"status": LoadTestConstants.STATUS_CREATED},
            {"status": "WEIRD"},
            {},
            {"status": LoadTestConstants.STATUS_TIMEOUT},
        ]

        counts: Dict[str, Any] = OutputValidator.count_results(results)

        self.assertEqual(sum(counts.values()), len(results))

    def test_stage_results_name_the_timeout_and_killed_limits(self) -> None:
        """
        The Timed out and Killed lines name the limits that give each status.
        """
        counts: Dict[str, Any] = OutputValidator.count_results([
            {"status": LoadTestConstants.STATUS_TIMEOUT},
            {"status": LoadTestConstants.STATUS_KILLED},
        ])

        with self.assertLogs(OutputValidator.__module__, level="INFO") as captured:
            OutputValidator.log_stage_results(2, counts, 4.0, 30.0, 10.0)

        output: str = "\n".join(captured.output)
        self.assertIn("Timed out: 1  (hit 30.0s hard cap or no output for 10.0s)", output)
        self.assertIn("Killed:  1  (still running at --stage-timeout or Ctrl-C)", output)
