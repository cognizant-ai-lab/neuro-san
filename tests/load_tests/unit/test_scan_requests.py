
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
import os
import shutil
import tempfile
from typing import Any
from typing import Dict
from unittest import TestCase

from tests.load_tests.config import STATUS_CREATED
from tests.load_tests.config import STATUS_FAILED
from tests.load_tests.config import STATUS_KILLED
from tests.load_tests.config import STATUS_TIMEOUT
from tests.load_tests.reporting.rebuild_results import ResultsRebuilder


# pylint: disable=protected-access
class TestScanRequests(TestCase):
    """
    Unit tests for the status of rebuilt request records.

    A timed-out or killed request usually printed a reservation_id
    before the client gave up, so partial output must not be read as
    evidence that the request succeeded.
    """

    def setUp(self) -> None:
        """Create a run directory removed again after each test."""
        self._dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self._dir)
        os.makedirs(os.path.join(self._dir, "requests"))

    def _write_request(self, req_id: int) -> None:
        """
        Write stdout for a request that got as far as reserving.

        :param req_id: Request id used in the file name and reservation id
        """
        path = os.path.join(
            self._dir, "requests", f"request_{req_id}_stdout.txt",
        )
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(
                '{"reservation_id": "abc-%s",'
                ' "agent_network_name": "music_nerd"}\n' % req_id
            )

    def _write_log(self, text: str) -> None:
        """
        Write the run log the rebuild reads timing from.

        :param text: Log text to write
        """
        path = os.path.join(self._dir, "load_test.log")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def _rebuild(self) -> Dict[str, Dict[str, Any]]:
        """
        Rebuild the run and return results keyed by request id.

        :return: Results keyed by request id
        """
        rebuilder = ResultsRebuilder(self._dir)
        results = rebuilder._scan_requests(
            os.path.join(self._dir, "requests"), rebuilder._parse_timing(),
        )
        keyed: Dict[str, Dict[str, Any]] = {}
        for result in results:
            keyed[result.get("request_id")] = result
        return keyed

    def test_partial_output_does_not_promote_a_timeout(self) -> None:
        """A TIMEOUT with a reservation_id stays a TIMEOUT."""
        self._write_request(1)
        self._write_log("Request 1: TIMEOUT (61.00s (1m))\n")

        self.assertEqual(
            self._rebuild()["request-1"]["status"], STATUS_TIMEOUT,
        )

    def test_partial_output_does_not_promote_a_kill(self) -> None:
        """A KILLED request with a reservation_id stays KILLED."""
        self._write_request(1)
        self._write_log("Request 1: KILLED (5.00s)\n")

        self.assertEqual(
            self._rebuild()["request-1"]["status"], STATUS_KILLED,
        )

    def test_partial_output_alone_is_not_success(self) -> None:
        """With no log line, partial output is not counted as passing."""
        self._write_request(1)
        self._write_log("")

        self.assertEqual(
            self._rebuild()["request-1"]["status"], STATUS_FAILED,
        )

    def test_successful_request_is_still_rebuilt_as_created(self) -> None:
        """The normal case is unaffected."""
        self._write_request(1)
        self._write_log("Request 1: CREATED (3.00s)\n")

        result = self._rebuild()["request-1"]

        self.assertEqual(result["status"], STATUS_CREATED)
        self.assertEqual(result["elapsed"], 3.0)
