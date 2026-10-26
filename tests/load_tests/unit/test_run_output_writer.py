
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
from json import load
from os.path import join
from shutil import rmtree
from tempfile import mkdtemp
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from unittest import TestCase
from unittest.mock import MagicMock
from unittest.mock import patch

from typing_extensions import override

from tests.load_tests.load_test_constants import LoadTestConstants
from tests.load_tests.reporting.resource_reporter import ResourceReporter
from tests.load_tests.reporting.run_log import RunLog
from tests.load_tests.reporting.run_output_writer import RunOutputWriter
from tests.load_tests.validation.server_checker import ServerChecker


class TestRunOutputWriter(TestCase):
    """
    Unit tests for RunOutputWriter.

    output_base(): the default lives in the shared temp directory, so it has to be
    per-user: a fixed name belongs to whoever ran first and everyone
    else gets a PermissionError creating their run directory.

    export_raw_json(): the same aggregate keys are written by a live run and by --rebuild,
    so they have to mean the same thing in both or a trend built from a mix of
    the two compares unlike numbers.
    """

    @override
    def setUp(self) -> None:
        """
        Create an output directory removed again after each test.
        """
        self._dir: str = mkdtemp()
        self.addCleanup(rmtree, self._dir)

    @staticmethod
    def _output_base_writer(output_dir: Optional[str] = None) -> RunOutputWriter:
        """
        Build a RunOutputWriter with only the args output_base() reads.

        :param output_dir: --output-dir value; None for the default
        :return: RunOutputWriter with only args set
        """
        args: Namespace = Namespace(output_dir=output_dir)
        output_parts: Dict[str, Any] = {}
        return RunOutputWriter(args, output_parts)

    def _export_writer(self) -> RunOutputWriter:
        """
        Build a RunOutputWriter with only what the export reads.

        :return: RunOutputWriter that writes to the scratch directory
        """
        args: Namespace = Namespace(
            agent="music_nerd", profile_path=None, level="norm",
            ramp=False, host="localhost", port=30011,
            request_timeout=120, idle_timeout=60, stage_timeout=300,
            total_timeout=600, settle_time=5, max_workers=10,
            num_rounds=1, num_requests=3, same_prompt=False,
            allow_caching=False, chat_filter=None,
            fixtures_hocon_dir=None, server_log=None, output_dir=self._dir,
        )
        server_checker: ServerChecker = ServerChecker(args)
        # The server version comes from /healthz; patch the fetch so the cached version is "0.6.92".
        with patch.object(ServerChecker, "fetch_server_version", return_value="0.6.92"):
            server_checker.resolve_ns_version()
        output_parts: Dict[str, Any] = {
            "server_checker": server_checker,
            "hocon_files": [],
            "resource_reporter": ResourceReporter(),
        }
        writer: RunOutputWriter = RunOutputWriter(args, output_parts)
        # Create the run directory under the scratch directory, without adding the run log handler.
        with patch.object(RunLog, "open"):
            writer.setup_test_log()
        return writer

    def _export(self, elapsed_values_seconds: List[float]) -> Dict[str, Any]:
        """
        Export one stage of successful requests and read it back.

        :param elapsed_values_seconds: Elapsed seconds, one per request
        :return: Aggregates read back from raw_results.json
        """
        results: List[Dict[str, Any]] = []
        index: int
        elapsed_seconds: float
        # One successful request per elapsed time, numbered from 1.
        for index, elapsed_seconds in enumerate(elapsed_values_seconds, start=1):
            result: Dict[str, Any] = {
                "request_id": f"request-{index}",
                "status": LoadTestConstants.STATUS_CREATED,
                "elapsed": elapsed_seconds,
            }
            results.append(result)
        # One stage whose wall-clock time is the slowest request,
        # because the requests ran concurrently.
        stage_summaries: List[Dict[str, Any]] = [{
            "concurrent": len(results),
            "results": results,
            "elapsed": max(elapsed_values_seconds),
        }]

        writer: RunOutputWriter = self._export_writer()
        writer.export_raw_json(stage_summaries, exit_code=0, estimated_tokens_per_request=1000)

        path: str = join(writer.get_output_dir(), LoadTestConstants.RAW_RESULTS_FILE_NAME)
        with open(path, "r", encoding="utf-8") as handle:
            raw_data: Dict[str, Any] = load(handle)
        aggregates: Dict[str, Any] = raw_data.get("aggregates", {})
        return aggregates

    @patch("tests.load_tests.reporting.run_output_writer.gettempdir")
    @patch("tests.load_tests.reporting.run_output_writer.getuser")
    def test_default_is_per_user(self, get_user: MagicMock, get_temp_dir: MagicMock) -> None:
        """
        The default path carries the user name, not a fixed one.

        :param get_user: Mock of getpass.getuser
        :param get_temp_dir: Mock of tempfile.gettempdir
        """
        get_user.return_value = "alice"
        get_temp_dir.return_value = "/tmp"

        self.assertEqual(TestRunOutputWriter._output_base_writer().output_base(), "/tmp/load_test_alice")

    @patch("tests.load_tests.reporting.run_output_writer.getuser")
    def test_output_dir_argument_wins(self, get_user: MagicMock) -> None:
        """
        --output-dir overrides the default without consulting the user.

        :param get_user: Mock of getpass.getuser; fails the test if called
        """
        get_user.side_effect = AssertionError("user name not needed")

        self.assertEqual(TestRunOutputWriter._output_base_writer(output_dir="/data/runs").output_base(), "/data/runs")

    @patch("tests.load_tests.reporting.run_output_writer.getuid")
    @patch("tests.load_tests.reporting.run_output_writer.gettempdir")
    @patch("tests.load_tests.reporting.run_output_writer.getuser")
    def test_falls_back_to_uid_without_passwd_entry(
        self, get_user: MagicMock, get_temp_dir: MagicMock, get_uid: MagicMock,
    ) -> None:
        """
        A uid with no passwd entry (containers) must not crash the run.

        :param get_user: Mock of getpass.getuser; raises KeyError
        :param get_temp_dir: Mock of tempfile.gettempdir
        :param get_uid: Mock of getuid
        """
        get_user.side_effect = KeyError("getpwuid(): uid not found")
        get_temp_dir.return_value = "/tmp"
        get_uid.return_value = 1000

        self.assertEqual(TestRunOutputWriter._output_base_writer().output_base(), "/tmp/load_test_1000")

    @patch("tests.load_tests.reporting.run_output_writer.gettempdir")
    @patch("tests.load_tests.reporting.run_output_writer.getuser")
    def test_user_name_cannot_inject_path_separators(self, get_user: MagicMock, get_temp_dir: MagicMock) -> None:
        """
        A domain-style name must stay one directory, not nest.

        :param get_user: Mock of getpass.getuser
        :param get_temp_dir: Mock of tempfile.gettempdir
        """
        get_user.return_value = "CORP\\alice"
        get_temp_dir.return_value = "/tmp"

        self.assertEqual(TestRunOutputWriter._output_base_writer().output_base(), "/tmp/load_test_CORP_alice")

    def test_average_latency_is_the_mean_request_time(self) -> None:
        """
        Concurrency must not divide the reported latency.

        Ten overlapping 30-second requests average 30 seconds, not the
        3 seconds that dividing wall-clock time by the request count
        would suggest.
        """
        aggregates: Dict[str, Any] = self._export([30.0] * 10)
        avg_latency_seconds: float = aggregates.get("avg_latency_seconds", 0.0)

        self.assertEqual(avg_latency_seconds, 30.0)

    def test_average_latency_reflects_uneven_requests(self) -> None:
        """
        The mean is taken over every request's own elapsed time.
        """
        aggregates: Dict[str, Any] = self._export([1.0, 2.0, 6.0])
        avg_latency_seconds: float = aggregates.get("avg_latency_seconds", 0.0)

        self.assertEqual(avg_latency_seconds, 3.0)

    def test_wall_clock_total_is_reported_separately(self) -> None:
        """
        Throughput is still derivable from the elapsed total.
        """
        aggregates: Dict[str, Any] = self._export([1.0, 2.0, 6.0])

        total_elapsed_seconds: float = aggregates.get("total_elapsed_seconds", 0.0)
        total_requests: int = aggregates.get("total_requests", 0)

        self.assertEqual(total_elapsed_seconds, 6.0)
        self.assertEqual(total_requests, 3)
