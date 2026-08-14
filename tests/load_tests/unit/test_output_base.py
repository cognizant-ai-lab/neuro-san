
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
from unittest import TestCase
from unittest.mock import patch

from tests.load_tests.load_test_cli import LoadTestOrchestrator


# These tests call a deliberately-internal helper directly; suppress
# protected-access warnings file-wide.
# pylint: disable=protected-access
class TestOutputBase(TestCase):
    """
    Unit tests for LoadTestOrchestrator._output_base().

    The default lives in the shared temp directory, so it has to be
    per-user: a fixed name belongs to whoever ran first and everyone
    else gets a PermissionError creating their run directory.
    """

    @staticmethod
    def _orchestrator(output_dir=None) -> LoadTestOrchestrator:
        """Build an orchestrator with only the args _output_base reads."""
        orchestrator = LoadTestOrchestrator.__new__(LoadTestOrchestrator)
        orchestrator.args = Namespace(output_dir=output_dir)
        return orchestrator

    @patch("tests.load_tests.load_test_cli.tempfile.gettempdir")
    @patch("tests.load_tests.load_test_cli.getpass.getuser")
    def test_default_is_per_user(self, get_user, get_temp_dir):
        """The default path carries the user name, not a fixed one."""
        get_user.return_value = "alice"
        get_temp_dir.return_value = "/tmp"

        self.assertEqual(
            self._orchestrator()._output_base(),
            "/tmp/load_test_alice",
        )

    @patch("tests.load_tests.load_test_cli.getpass.getuser")
    def test_output_dir_argument_wins(self, get_user):
        """--output-dir overrides the default without consulting the user."""
        get_user.side_effect = AssertionError("user name not needed")

        self.assertEqual(
            self._orchestrator(output_dir="/data/runs")._output_base(),
            "/data/runs",
        )

    @patch("tests.load_tests.load_test_cli.os.getuid")
    @patch("tests.load_tests.load_test_cli.tempfile.gettempdir")
    @patch("tests.load_tests.load_test_cli.getpass.getuser")
    def test_falls_back_to_uid_without_passwd_entry(
        self, get_user, get_temp_dir, get_uid,
    ):
        """A uid with no passwd entry (containers) must not crash the run."""
        get_user.side_effect = KeyError("getpwuid(): uid not found")
        get_temp_dir.return_value = "/tmp"
        get_uid.return_value = 1000

        self.assertEqual(
            self._orchestrator()._output_base(),
            "/tmp/load_test_1000",
        )

    @patch("tests.load_tests.load_test_cli.tempfile.gettempdir")
    @patch("tests.load_tests.load_test_cli.getpass.getuser")
    def test_user_name_cannot_inject_path_separators(
        self, get_user, get_temp_dir,
    ):
        """A domain-style name must stay one directory, not nest."""
        get_user.return_value = "CORP\\alice"
        get_temp_dir.return_value = "/tmp"

        self.assertEqual(
            self._orchestrator()._output_base(),
            "/tmp/load_test_CORP_alice",
        )
