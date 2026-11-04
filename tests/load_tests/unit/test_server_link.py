
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

from typing import Optional
from unittest import TestCase

from tests.load_tests.monitoring.server_link import ServerLink
from tests.load_tests.monitoring.server_log_monitor import ServerLogMonitor
from tests.load_tests.monitoring.tracked_process import TrackedProcess
from tests.load_tests.validation.server_checker import ServerChecker


class TestServerLink(TestCase):
    """
    Unit tests for ServerLink: the server log path, its log monitor, the server process and the ServerChecker.
    """

    def test_no_server_log_has_no_log_monitor(self) -> None:
        """
        Without --server-log there is no log monitor and no server process, and there is a ServerChecker.
        """
        server_link: ServerLink = ServerLink(None, ServerChecker("localhost", 8080, False))
        server_log: Optional[str] = server_link.get_server_log()
        log_monitor: Optional[ServerLogMonitor] = server_link.get_log_monitor()
        server_process: Optional[TrackedProcess] = server_link.get_server_process()
        self.assertIsNone(server_log)
        self.assertIsNone(log_monitor)
        self.assertIsNone(server_process)
        server_checker: ServerChecker = server_link.get_server_checker()
        self.assertIsInstance(server_checker, ServerChecker)

    def test_set_server_makes_a_log_monitor_for_the_resolved_log(self) -> None:
        """
        set_server() keeps the resolved --server-log path and makes a log monitor for it.
        """
        server_link: ServerLink = ServerLink("auto", ServerChecker("localhost", 8080, False))
        server_link.set_server(None, "/tmp/neuro_san_server.log")
        server_log: Optional[str] = server_link.get_server_log()
        log_monitor: Optional[ServerLogMonitor] = server_link.get_log_monitor()
        self.assertEqual(server_log, "/tmp/neuro_san_server.log")
        self.assertIsNotNone(log_monitor)
