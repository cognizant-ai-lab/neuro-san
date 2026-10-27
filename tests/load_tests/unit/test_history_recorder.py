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
from json import loads
from os import environ
from os import listdir
from os.path import dirname
from os.path import join
from tempfile import TemporaryDirectory
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from unittest import TestCase
from unittest.mock import patch

from tests.load_tests.load_test_constants import LoadTestConstants
from tests.load_tests.reporting.history_recorder import HistoryRecorder


class TestHistoryRecorder(TestCase):
    """
    Tests for HistoryRecorder: history file paths and the client and server-only trend records.
    """

    def test_history_paths_default_to_output_base(self) -> None:
        """
        Without --history-file the files are history.jsonl and history_unknown.jsonl in the output base.
        """
        args: Namespace = Namespace(history_file=None, host="localhost", agent="hello_world")
        recorder: HistoryRecorder = HistoryRecorder(args, "/tmp/base")
        self.assertEqual(recorder.get_history_path(), "/tmp/base/history.jsonl")
        self.assertEqual(recorder.get_history_path(successful=False), "/tmp/base/history_unknown.jsonl")

    def test_history_paths_from_history_file(self) -> None:
        """
        With --history-file the unknown records go to a sibling "_unknown" file.
        """
        args: Namespace = Namespace(history_file="/tmp/h/trend.jsonl", host="h", agent="a")
        recorder: HistoryRecorder = HistoryRecorder(args, "/tmp/base")
        self.assertEqual(recorder.get_history_path(), "/tmp/h/trend.jsonl")
        self.assertEqual(recorder.get_history_path(successful=False), "/tmp/h/trend_unknown.jsonl")

    def test_append_client_record(self) -> None:
        """
        A client run with a known version writes counts, averages and threshold counts to history.jsonl.
        """
        records: List[Dict[str, Any]] = []
        with TemporaryDirectory() as base:
            args: Namespace = Namespace(history_file=None, host="localhost", agent="hello_world")
            recorder: HistoryRecorder = HistoryRecorder(args, base)
            stage_summaries: List[Dict[str, Any]] = [
                {
                    "elapsed": 4.0,
                    "results": [
                        {"status": "CREATED", "elapsed": 2.0, "time_to_first_response": 1.0},
                        {"status": "FAILED", "elapsed": 9.0},
                    ],
                },
                {
                    "elapsed": 3.5,
                    "results": [{"status": "CREATED", "elapsed": 4.0, "time_to_first_response": 2.0}],
                    "server_errors": [{"message": "boom"}],
                },
            ]
            recorder.append_client_record(stage_summaries, "0.6.92")
            history_path: str = join(base, LoadTestConstants.HISTORY_FILE_NAME)
            records = TestHistoryRecorder._read_records(history_path)
        record_count: int = len(records)
        self.assertEqual(record_count, 1)
        record: Dict[str, Any] = records[0]
        expected_values: Dict[str, Any] = {
            "total_requests": 3,
            "completed": 2,
            "avg_duration_s": 3.0,
            "avg_first_response_s": 1.5,
            "wall_time_s": 7.5,
            "server_error_count": 1,
            "neuro_san_version": "0.6.92",
        }
        self._assert_record_values(record, expected_values)

    def test_append_client_record_without_results(self) -> None:
        """
        A client run with no results writes no file.
        """
        with TemporaryDirectory() as base:
            args: Namespace = Namespace(history_file=None, host="localhost", agent="hello_world")
            recorder: HistoryRecorder = HistoryRecorder(args, base)
            recorder.append_client_record([{"results": []}], "0.6.92")
            entries: List[str] = listdir(base)
            self.assertEqual(entries, [])

    def test_append_server_record_unknown_version(self) -> None:
        """
        A server-only round with no version goes to history_unknown.jsonl, with the server-side timings.
        """
        records: List[Dict[str, Any]] = []
        with TemporaryDirectory() as base:
            args: Namespace = Namespace(history_file=None, host="localhost", agent="hello_world")
            recorder: HistoryRecorder = HistoryRecorder(args, base)
            primary_pairs: List[Dict[str, Any]] = [
                {"duration_seconds": 2.0, "start_ts": 10.0, "finish_ts": 12.0},
                {"duration_seconds": 4.0, "start_ts": 11.0, "finish_ts": 15.0},
            ]
            round_record: Dict[str, Any] = TestHistoryRecorder._server_round(None, primary_pairs)
            recorder.append_server_record(round_record)
            history_path: str = join(base, LoadTestConstants.HISTORY_UNKNOWN_FILE_NAME)
            records = TestHistoryRecorder._read_records(history_path)
        record: Dict[str, Any] = records[0]
        expected_values: Dict[str, Any] = {
            "mode": "server-only",
            "neuro_san_version": "unknown",
            "avg_duration_s": 3.0,
            "time_to_first_completed_s": 2.0,
            "peak_memory_gb": 2.0,
            "peak_cpu_cores": 0.0,
        }
        self._assert_record_values(record, expected_values)

    def test_write_failure_logs_the_error(self) -> None:
        """
        When the history file cannot be written, the warning holds the path and the error text.
        """
        with TemporaryDirectory() as base:
            blocker_path: str = join(base, "blocker")
            output: List[str] = self._failed_write_output("true", blocker_path)
        history_path: str = join(blocker_path, LoadTestConstants.HISTORY_FILE_NAME)
        expected_line: str = ("WARNING:HistoryRecorder:  Could not write trend history"
                              f" to {history_path}: [Errno 17] File exists: '{blocker_path}'")
        self.assertEqual(output, [expected_line])

    def test_write_failure_hides_the_error_when_sensitive_logging_is_off(self) -> None:
        """
        With LEAF_LOG_SENSITIVE=false the warning holds the path and no error text.
        """
        with TemporaryDirectory() as base:
            blocker_path: str = join(base, "blocker")
            output: List[str] = self._failed_write_output("false", blocker_path)
        history_path: str = join(blocker_path, LoadTestConstants.HISTORY_FILE_NAME)
        expected_line: str = f"WARNING:HistoryRecorder:  Could not write trend history to {history_path}"
        self.assertEqual(output, [expected_line])

    def test_log_existing_history_files(self) -> None:
        """
        Only the history files that exist are logged, each with its path.
        """
        history_path: str = ""
        with TemporaryDirectory() as base:
            args: Namespace = Namespace(history_file=None, host="localhost", agent="hello_world")
            recorder: HistoryRecorder = HistoryRecorder(args, base)
            history_path = join(base, LoadTestConstants.HISTORY_FILE_NAME)
            with open(history_path, "w", encoding="utf-8") as history_file:
                history_file.write("{}\n")
            with self.assertLogs("HistoryRecorder", level="INFO") as captured:
                recorder.log_existing_history_files()
        expected_line: str = f"INFO:HistoryRecorder:  History:     {history_path}"
        self.assertEqual(captured.output, [expected_line])

    def _failed_write_output(self, log_sensitive: str, blocker_path: str) -> List[str]:
        """
        Append a server-only record to blocker_path/history.jsonl, where blocker_path is a plain file, so the
        write fails.

        :param log_sensitive: The LEAF_LOG_SENSITIVE value for the run: "true" or "false"
        :param blocker_path: Path of the plain file to create in a temporary folder
        :return: The WARNING lines the history recorder logs
        """
        with open(blocker_path, "w", encoding="utf-8") as blocker_file:
            blocker_file.write("not a folder\n")
        history_path: str = join(blocker_path, LoadTestConstants.HISTORY_FILE_NAME)
        args: Namespace = Namespace(history_file=history_path, host="localhost", agent="hello_world")
        output_base: str = dirname(blocker_path)
        round_record: Dict[str, Any] = TestHistoryRecorder._server_round("1.0.0", [])
        with patch.dict(environ, {"LEAF_LOG_SENSITIVE": log_sensitive}), \
                self.assertLogs("HistoryRecorder", level="WARNING") as captured:
            # The SensitiveLogger reads LEAF_LOG_SENSITIVE when it is built, inside append_server_record().
            recorder: HistoryRecorder = HistoryRecorder(args, output_base)
            recorder.append_server_record(round_record)
        output: List[str] = captured.output
        return output

    @staticmethod
    def _server_round(neuro_san_version: Optional[str], primary_pairs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Build the server-only round dict that append_server_record() takes: 2 of 2 requests in 6 seconds.

        :param neuro_san_version: Server neuro-san version, or None when unknown
        :param primary_pairs: Primary agent Start/Finish pairs
        :return: The round dict
        """
        round_record: Dict[str, Any] = {
            "neuro_san_version": neuro_san_version,
            "expected": 2,
            "count": 2,
            "elapsed_seconds": 6.0,
            "peak_server": {"rss_megabytes": 2048.0},
            "peak_system_cpu_percent": None,
            "primary_pairs": primary_pairs,
            "server_errors": None,
            "tool_warnings": None,
        }
        return round_record

    def _assert_record_values(self, record: Dict[str, Any], expected_values: Dict[str, Any]) -> None:
        """
        Check that each expected field of a history record has its expected value.

        :param record: One record read from a history file
        :param expected_values: Field name to the value the record must hold
        """
        key: str
        # Compare each expected field with the value in the record.
        for key in expected_values.keys():
            actual_value: Any = record.get(key)
            expected_value: Any = expected_values.get(key)
            self.assertEqual(actual_value, expected_value, key)

    @staticmethod
    def _read_records(path: str) -> List[Dict[str, Any]]:
        """
        Read the JSONL records of a history file.

        :param path: History file path
        :return: The records in file order
        """
        records: List[Dict[str, Any]] = []
        with open(path, "r", encoding="utf-8") as history_file:
            line: str
            # Parse each line of the file as one record.
            for line in history_file:
                record: Dict[str, Any] = loads(line)
                records.append(record)
        return records
