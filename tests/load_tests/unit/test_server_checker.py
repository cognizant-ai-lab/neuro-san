
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
from os import environ
from typing import Any
from typing import Optional
from unittest import TestCase
from unittest.mock import MagicMock
from unittest.mock import patch

from tests.load_tests.validation.load_test_abort_error import LoadTestAbortError
from tests.load_tests.validation.server_checker import ServerChecker


class TestServerChecker(TestCase):
    """
    Unit tests for ServerChecker: the version cache, package versions and the --server-log check.
    """

    def test_resolve_ns_version_fetches_once_and_caches(self) -> None:
        """
        The first call fetches the version from /healthz; later calls read the cache.
        """
        args: Namespace = TestServerChecker._args(None)
        server_checker: ServerChecker = ServerChecker(args)
        fetch_patch: Any = patch.object(ServerChecker, "fetch_server_version", return_value="0.6.92")
        fetch_mock: MagicMock = fetch_patch.start()
        self.addCleanup(fetch_patch.stop)
        first_version: Optional[str] = server_checker.resolve_ns_version()
        second_version: Optional[str] = server_checker.resolve_ns_version()
        cached_version: Optional[str] = server_checker.get_server_ns_version()
        self.assertEqual(first_version, "0.6.92")
        self.assertEqual(second_version, "0.6.92")
        self.assertEqual(cached_version, "0.6.92")
        self.assertEqual(fetch_mock.call_count, 1)

    def test_fetch_server_version_of_unreachable_server_is_none(self) -> None:
        """
        Nothing listens on port 1, so there is no version.
        """
        args: Namespace = TestServerChecker._args(None, port=1)
        server_checker: ServerChecker = ServerChecker(args)
        server_version: Optional[str] = server_checker.fetch_server_version()
        self.assertIsNone(server_version)

    def test_fetch_failure_logs_the_url_and_only_the_error_type(self) -> None:
        """
        With LEAF_LOG_SENSITIVE=false the debug line names the URL and only the error type.
        """
        args: Namespace = TestServerChecker._args(None, port=1)
        with patch.dict(environ, {"LEAF_LOG_SENSITIVE": "false"}), \
                self.assertLogs("tests.load_tests.validation.server_checker", level="DEBUG") as captured:
            # Built inside patch.dict: the checker reads LEAF_LOG_SENSITIVE when it is built.
            server_checker: ServerChecker = ServerChecker(args)
            server_checker.fetch_server_version()
        expected_line: str = ("DEBUG:tests.load_tests.validation.server_checker:Could not fetch server version"
                              " from http://localhost:1/healthz: URLError")
        self.assertEqual(captured.output, [expected_line])

    def test_get_package_version(self) -> None:
        """
        An installed package has a version; a missing one has None.
        """
        installed_version: Optional[str] = ServerChecker.get_package_version("psutil")
        missing_version: Optional[str] = ServerChecker.get_package_version("no-such-package-for-load-tests")
        self.assertIsNotNone(installed_version)
        self.assertIsNone(missing_version)

    def test_validate_server_log_auto_is_not_checked(self) -> None:
        """
        "auto" means the log is found later, so there is nothing to check yet.
        """
        args: Namespace = TestServerChecker._args("auto")
        server_checker: ServerChecker = ServerChecker(args)
        stale_age_minutes: Optional[int] = server_checker.validate_server_log()
        self.assertIsNone(stale_age_minutes)

    def test_validate_server_log_missing_file_aborts(self) -> None:
        """
        A --server-log path that does not exist stops the run with exit code 1.
        """
        args: Namespace = TestServerChecker._args("/no/such/dir/server.log")
        server_checker: ServerChecker = ServerChecker(args)
        with self.assertRaises(LoadTestAbortError) as context:
            server_checker.validate_server_log()
        exit_code: int = context.exception.get_exit_code()
        self.assertEqual(exit_code, 1)

    @staticmethod
    def _args(server_log: Optional[str], port: int = 30011) -> Namespace:
        """
        Build the parsed arguments that ServerChecker reads, for a local server.

        :param server_log: The --server-log value, or None
        :param port: The --port value
        :return: The arguments
        """
        return Namespace(host="localhost", port=port, https=False, level="norm", server_log=server_log)
