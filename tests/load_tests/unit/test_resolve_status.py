
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
from unittest import TestCase

from tests.load_tests.config import STATUS_CREATED
from tests.load_tests.config import STATUS_FAILED
from tests.load_tests.config import STATUS_KILLED
from tests.load_tests.config import STATUS_TIMEOUT
from tests.load_tests.reporting.rebuild_results import ResultsRebuilder


# These tests call deliberately-internal helpers directly; suppress
# protected-access warnings file-wide.
# pylint: disable=protected-access
class TestResolveStatus(TestCase):
    """
    Unit tests for ResultsRebuilder._resolve_status().

    --rebuild reconstructs a run's verdict after an interrupted run, so
    a request must come back with the status the run actually reported.
    """

    def test_each_reported_status_is_preserved(self):
        """CREATED, FAILED, TIMEOUT and KILLED all survive a rebuild."""
        for status in (
            STATUS_CREATED, STATUS_FAILED, STATUS_TIMEOUT, STATUS_KILLED,
        ):
            with self.subTest(status=status):
                self.assertEqual(
                    ResultsRebuilder._resolve_status({"status": status}),
                    status,
                )

    def test_missing_log_line_counts_as_failed(self):
        """A request never seen to finish is a failure, not a success.

        Failures past FAILURE_LOG_LIMIT are never printed, so an absent
        log line is the normal case for a heavily failing run.
        """
        self.assertEqual(
            ResultsRebuilder._resolve_status({}), STATUS_FAILED,
        )

    def test_unrecognized_status_counts_as_failed(self):
        """An unknown status word is never promoted to success."""
        self.assertEqual(
            ResultsRebuilder._resolve_status({"status": "WEIRD"}),
            STATUS_FAILED,
        )
