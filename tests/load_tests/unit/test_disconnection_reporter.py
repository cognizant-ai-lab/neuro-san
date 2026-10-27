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

from tests.load_tests.reporting.disconnection_reporter import DisconnectionReporter


class TestDisconnectionReporter(TestCase):
    """
    Unit tests for DisconnectionReporter.log_disconnection_summary().
    """

    def test_each_disconnection_is_listed_with_the_timeout_hint(self) -> None:
        """
        Each disconnection gets a line with its batch, and the hint names the timeouts that end a stream.
        """
        stage_summaries: List[Dict[str, Any]] = [
            {"disconnections": []},
            {"disconnections": [{"request_id": "req-1", "agent": "hello_world"}]},
        ]
        reporter: DisconnectionReporter = DisconnectionReporter(stage_summaries)

        with self.assertLogs(DisconnectionReporter.__name__, level="INFO") as captured:
            reporter.log_disconnection_summary()

        output: str = "\n".join(captured.output)
        self.assertIn("CLIENT DISCONNECTIONS (1 detected in server log)", output)
        self.assertIn("Batch 2: req-1 — hello_world still processing at disconnect", output)
        self.assertIn("If unexpected, consider increasing --idle-timeout or --request-timeout.", output)

    def test_no_disconnections_logs_nothing(self) -> None:
        """
        A run with no disconnections adds no section to the report.
        """
        stage_summaries: List[Dict[str, Any]] = [{"disconnections": None}, {}]
        reporter: DisconnectionReporter = DisconnectionReporter(stage_summaries)

        with self.assertNoLogs(DisconnectionReporter.__name__, level="INFO"):
            reporter.log_disconnection_summary()
