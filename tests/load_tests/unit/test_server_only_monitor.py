
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
from shutil import rmtree
from tempfile import mkdtemp
from typing import Any
from typing import Dict
from unittest import TestCase
from unittest.mock import patch

from typing_extensions import override

from tests.load_tests.monitoring.server_only_monitor import ServerOnlyMonitor
from tests.load_tests.prompts.agent_profile import AgentProfile
from tests.load_tests.validation.server_checker import ServerChecker


class TestServerOnlyMonitor(TestCase):
    """
    Unit tests for ServerOnlyMonitor: leaving the prompt loop.
    """

    @override
    def setUp(self) -> None:
        """
        Make a scratch output directory and a monitor with no server process and no server log.
        """
        self._dir: str = mkdtemp()
        server_checker: ServerChecker = ServerChecker("localhost", 30011, False)
        monitor_parts: Dict[str, Any] = {
            "server_process": None,
            "log_monitor": None,
            "history_recorder": None,
            "server_checker": server_checker,
            "agent": "music_nerd",
            "host": "localhost",
            "server_log": None,
            "stage_timeout_seconds": 30,
        }
        profile: AgentProfile = AgentProfile("hello_world", {"estimated_tokens_per_request": 1000})
        self._monitor: ServerOnlyMonitor = ServerOnlyMonitor(profile, monitor_parts)

    @override
    def tearDown(self) -> None:
        """
        Remove the scratch output directory.
        """
        rmtree(self._dir, ignore_errors=True)

    def test_run_exits_with_zero_at_end_of_input(self) -> None:
        """
        End of input at the request-count prompt ends server-only mode with exit code 0.
        """
        with patch("builtins.input", side_effect=EOFError):
            exit_code: int = self._monitor.run(self._dir)
        self.assertEqual(exit_code, 0)
