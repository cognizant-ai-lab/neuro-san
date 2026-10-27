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

from json import dumps
from os import close
from os import environ
from os import unlink
from os.path import join
from shutil import rmtree
from tempfile import mkdtemp
from tempfile import mkstemp
from typing import Any
from typing import Dict
from typing import List
from unittest import TestCase
from unittest.mock import patch

from typing_extensions import override

from tests.load_tests.load_test_constants import LoadTestConstants
from tests.load_tests.reporting.trend_history import TrendHistory


# These tests read deliberately-internal helpers directly; suppress
# protected-access warnings file-wide.
# pylint: disable=protected-access
class TestTrendHistory(TestCase):
    """
    Unit tests for TrendHistory: _read_records() and _resolve_path().

    The history file is append-only and grows one record per run, so a
    single malformed line -- expected whenever a run is interrupted
    mid-write -- must not cost the user every earlier data point.
    --trend accepts either the history file or the output directory
    holding it, because both are printed at the end of a run.
    """

    MISSING_HISTORY_PATH: str = join("/nonexistent", LoadTestConstants.HISTORY_FILE_NAME)

    @override
    def setUp(self) -> None:
        """
        Create a scratch history file and a scratch directory, removed again after each test.
        """
        file_descriptor: int = 0
        self._history_path: str = ""
        file_descriptor, self._history_path = mkstemp(suffix=".jsonl")
        close(file_descriptor)
        self.addCleanup(unlink, self._history_path)
        self._output_dir: str = mkdtemp()
        self.addCleanup(rmtree, self._output_dir)

    def test_records_are_read_in_file_order(self) -> None:
        """
        Every well-formed line becomes one record.
        """
        history_text: str = dumps({"agent": "one"}) + "\n" + dumps({"agent": "two"}) + "\n"
        self._write(history_text)

        trend_history: TrendHistory = TrendHistory(self._history_path)
        records: List[Dict[str, Any]] = trend_history._read_records(self._history_path)

        agents: List[str] = TestTrendHistory._agents(records)

        self.assertEqual(agents, ["one", "two"])

    def test_truncated_final_line_does_not_lose_earlier_records(self) -> None:
        """
        An interrupted run leaves a partial line; the rest survives.
        """
        history_text: str = dumps({"agent": "one"}) + "\n" + '{"agent": "two", "requ'
        self._write(history_text)

        trend_history: TrendHistory = TrendHistory(self._history_path)
        records: List[Dict[str, Any]] = trend_history._read_records(self._history_path)

        agents: List[str] = TestTrendHistory._agents(records)

        self.assertEqual(agents, ["one"])

    def test_blank_lines_are_skipped(self) -> None:
        """
        Blank lines are not counted as records.
        """
        history_text: str = "\n" + dumps({"agent": "one"}) + "\n\n"
        self._write(history_text)

        trend_history: TrendHistory = TrendHistory(self._history_path)
        records: List[Dict[str, Any]] = trend_history._read_records(self._history_path)
        record_count: int = len(records)

        self.assertEqual(record_count, 1)

    def test_non_object_lines_are_skipped(self) -> None:
        """
        Valid JSON that is not an object cannot be a record.
        """
        history_text: str = "[1, 2, 3]\n" + dumps({"agent": "one"}) + "\n"
        self._write(history_text)

        trend_history: TrendHistory = TrendHistory(self._history_path)
        records: List[Dict[str, Any]] = trend_history._read_records(self._history_path)

        agents: List[str] = TestTrendHistory._agents(records)

        self.assertEqual(agents, ["one"])

    def test_unreadable_file_yields_nothing(self) -> None:
        """
        A missing file warns and returns empty rather than raising.
        """
        with self.assertLogs("TrendHistory", level="WARNING") as captured_logs:
            trend_history: TrendHistory = TrendHistory(TestTrendHistory.MISSING_HISTORY_PATH)
            records: List[Dict[str, Any]] = trend_history._read_records(TestTrendHistory.MISSING_HISTORY_PATH)
        self.assertEqual(records, [])
        expected_text: str = f"Could not read history file {TestTrendHistory.MISSING_HISTORY_PATH}"
        self.assertIn(expected_text, captured_logs.output[0])

    def test_unreadable_file_warning_shows_only_the_error_type_when_sensitive_logging_is_off(self) -> None:
        """
        With LEAF_LOG_SENSITIVE=false the warning names the file and only the error type.
        """
        with patch.dict(environ, {"LEAF_LOG_SENSITIVE": "false"}), \
                self.assertLogs("TrendHistory", level="WARNING") as captured_logs:
            trend_history: TrendHistory = TrendHistory(TestTrendHistory.MISSING_HISTORY_PATH)
            trend_history._read_records(TestTrendHistory.MISSING_HISTORY_PATH)
        expected_line: str = (f"WARNING:TrendHistory:Could not read history file "
                              f"{TestTrendHistory.MISSING_HISTORY_PATH}: FileNotFoundError")
        self.assertEqual(captured_logs.output, [expected_line])

    def test_a_file_path_is_used_directly(self) -> None:
        """
        Passing the history file itself resolves to that file.
        """
        path: str = self._create_history()

        self.assertEqual(TrendHistory(path)._resolve_path(), path)

    def test_a_directory_resolves_to_its_history_file(self) -> None:
        """
        Passing the output directory finds history.jsonl inside it.
        """
        path: str = self._create_history()

        self.assertEqual(TrendHistory(self._output_dir)._resolve_path(), path)

    def test_missing_history_resolves_to_none(self) -> None:
        """
        A directory with no history file resolves to None.
        """
        self.assertIsNone(TrendHistory(self._output_dir)._resolve_path())

    def _write(self, text: str) -> None:
        """
        Write the given text to the scratch history file.

        :param text: History file contents
        """
        with open(self._history_path, "w", encoding="utf-8") as file_handle:
            file_handle.write(text)

    @staticmethod
    def _agents(records: List[Dict[str, Any]]) -> List[str]:
        """
        Get the agent of each record, in file order.

        :param records: Records read from the history file
        :return: The "agent" of each record, "" if missing
        """
        agents: List[str] = []
        record: Dict[str, Any]
        # Collect the agent of each record, in file order.
        for record in records:
            agents.append(record.get("agent", ""))
        return agents

    def _create_history(self) -> str:
        """
        Create a default-named history file in the scratch directory.

        :return: Path of the created file
        """
        path: str = join(self._output_dir, LoadTestConstants.HISTORY_FILE_NAME)
        with open(path, "w", encoding="utf-8") as handle:
            history_text: str = dumps({"agent": "one"}) + "\n"
            handle.write(history_text)
        return path
