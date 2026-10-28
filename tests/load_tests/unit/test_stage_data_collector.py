
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
from typing import Optional
from unittest import TestCase
from unittest.mock import patch

from tests.load_tests.load_test_constants import LoadTestConstants
from tests.load_tests.reporting.stage_data_collector import StageDataCollector


class TestStageDataCollector(TestCase):
    """
    Unit tests for StageDataCollector: the settle line after a stage.
    """

    def test_settle_line_prints_minutes_and_seconds(self) -> None:
        """
        A 105 second --settle-time is logged as "1m 45s", and without a server process there is no server snapshot.
        """
        collector_parts: Dict[str, Any] = {
            "profile": None,
            "log_monitor": None,
            "resource_reporter": None,
            "server_process": None,
            "output_dir": None,
            "agent": None,
            "level": LoadTestConstants.LEVEL_MIN,
            "client_only": True,
            "settle_time_seconds": 105,
        }
        data_collector: StageDataCollector = StageDataCollector(collector_parts)
        post_stage_inputs: Dict[str, Any] = {
            "actual_requests": 0,
            "monitor_resources": True,
            "has_server_log": False,
            "log_position": None,
            "results": [],
            "before_server": None,
            "before_client": None,
            "peak_client": None,
            "settled_client": None,
            "server_log_requests": None,
        }
        post_stage_data: Dict[str, Any] = {}
        # sleep() is patched so the test does not wait out the settle time.
        with patch("tests.load_tests.reporting.stage_data_collector.sleep"):
            with self.assertLogs(data_collector.logger, level="INFO") as captured:
                post_stage_data = data_collector.collect_post_stage_data(post_stage_inputs)
        after_server: Optional[Dict[str, Any]] = post_stage_data.get("after_server")
        log_text: str = "\n".join(captured.output)
        self.assertIn("Settle: waited 1m 45s for server cleanup", log_text)
        self.assertIsNone(after_server)
