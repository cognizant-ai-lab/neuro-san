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

from argparse import Namespace
from typing import Optional

from psutil import Process

from tests.load_tests.monitoring.server_log_monitor import ServerLogMonitor
from tests.load_tests.validation.server_checker import ServerChecker


class ServerLink:
    """
    The server under test, as the client side sees it: the local server process (None when the server is
    remote or not looked up), the --server-log path (None when there is no log), the log monitor of that path
    and the ServerChecker that checks the server.
    """

    def __init__(self, args: Namespace) -> None:
        """
        Keep the --server-log path, make its log monitor and the ServerChecker. The server process is set later
        by set_server().

        :param args: Parsed command-line arguments
        """
        server_log: Optional[str] = args.server_log
        self._server_checker: ServerChecker = ServerChecker(args)
        self._server_process: Optional[Process] = None
        self._server_log: Optional[str] = server_log
        self._log_monitor: Optional[ServerLogMonitor] = None
        if server_log:
            self._log_monitor = ServerLogMonitor(server_log)

    def set_server(self, server_process: Optional[Process], server_log: Optional[str]) -> None:
        """
        Keep the server process and the resolved --server-log path, and make a new log monitor for that path.

        :param server_process: The local server process, or None
        :param server_log: The resolved --server-log path, or None
        """
        self._server_process = server_process
        self._server_log = server_log
        if server_log:
            self._log_monitor = ServerLogMonitor(server_log)

    def get_server_process(self) -> Optional[Process]:
        """
        :return: The local server process, or None
        """
        return self._server_process

    def get_server_log(self) -> Optional[str]:
        """
        :return: The --server-log path, or None
        """
        return self._server_log

    def get_log_monitor(self) -> Optional[ServerLogMonitor]:
        """
        :return: The log monitor of the --server-log path, or None
        """
        return self._log_monitor

    def get_server_checker(self) -> ServerChecker:
        """
        :return: The ServerChecker of the server under test
        """
        return self._server_checker
