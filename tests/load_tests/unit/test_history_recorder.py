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
import json
import os
import tempfile
from argparse import Namespace
from typing import Any
from typing import Dict
from typing import List
from unittest import TestCase

from tests.load_tests.reporting.history_recorder import HistoryRecorder


class TestHistoryRecorder(TestCase):
    """
    Tests for HistoryRecorder: history file paths and the client and server-only trend records.
    """

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
                record: Dict[str, Any] = json.loads(line)
                records.append(record)
        return records

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
        with tempfile.TemporaryDirectory() as base:
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
            records: List[Dict[str, Any]] = self._read_records(os.path.join(base, "history.jsonl"))
        self.assertEqual(len(records), 1)
        record: Dict[str, Any] = records[0]
        self.assertEqual(record.get("total_requests"), 3)
        self.assertEqual(record.get("completed"), 2)
        self.assertEqual(record.get("avg_duration_s"), 3.0)
        self.assertEqual(record.get("avg_first_response_s"), 1.5)
        self.assertEqual(record.get("wall_time_s"), 7.5)
        self.assertEqual(record.get("server_error_count"), 1)
        self.assertEqual(record.get("neuro_san_version"), "0.6.92")

    def test_append_client_record_without_results(self) -> None:
        """
        A client run with no results writes no file.
        """
        with tempfile.TemporaryDirectory() as base:
            args: Namespace = Namespace(history_file=None, host="localhost", agent="hello_world")
            recorder: HistoryRecorder = HistoryRecorder(args, base)
            recorder.append_client_record([{"results": []}], "0.6.92")
            self.assertEqual(os.listdir(base), [])

    def test_append_server_record_unknown_version(self) -> None:
        """
        A server-only round with no version goes to history_unknown.jsonl, with the server-side timings.
        """
        with tempfile.TemporaryDirectory() as base:
            args: Namespace = Namespace(history_file=None, host="localhost", agent="hello_world")
            recorder: HistoryRecorder = HistoryRecorder(args, base)
            primary_pairs: List[Dict[str, Any]] = [
                {"duration_seconds": 2.0, "start_ts": 10.0, "finish_ts": 12.0},
                {"duration_seconds": 4.0, "start_ts": 11.0, "finish_ts": 15.0},
            ]
            recorder.append_server_record(None, 2, 2, 6.0, {"rss": 2048.0}, None, primary_pairs, None, None)
            records: List[Dict[str, Any]] = self._read_records(os.path.join(base, "history_unknown.jsonl"))
        record: Dict[str, Any] = records[0]
        self.assertEqual(record.get("mode"), "server-only")
        self.assertEqual(record.get("neuro_san_version"), "unknown")
        self.assertEqual(record.get("avg_duration_s"), 3.0)
        self.assertEqual(record.get("time_to_first_completed_s"), 2.0)
        self.assertEqual(record.get("peak_memory_gb"), 2.0)
        self.assertEqual(record.get("peak_cpu_cores"), 0.0)

    def test_log_existing_history_files(self) -> None:
        """
        Only the history files that exist are logged, each with its path.
        """
        with tempfile.TemporaryDirectory() as base:
            args: Namespace = Namespace(history_file=None, host="localhost", agent="hello_world")
            recorder: HistoryRecorder = HistoryRecorder(args, base)
            history_path: str = os.path.join(base, "history.jsonl")
            with open(history_path, "w", encoding="utf-8") as history_file:
                history_file.write("{}\n")
            with self.assertLogs("tests.load_tests.reporting.history_recorder", level="INFO") as captured:
                recorder.log_existing_history_files()
        expected_line: str = f"INFO:tests.load_tests.reporting.history_recorder:  History:     {history_path}"
        self.assertEqual(captured.output, [expected_line])
