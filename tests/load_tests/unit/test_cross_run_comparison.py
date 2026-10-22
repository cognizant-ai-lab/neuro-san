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
from json import JSONDecodeError
from json import dumps
from os.path import join
from shutil import rmtree
from tempfile import mkdtemp
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
from typing import Union
from unittest import TestCase
from unittest.mock import MagicMock
from unittest.mock import patch

from typing_extensions import override

from tests.load_tests.load_test_constants import RAW_RESULTS_FILE_NAME
from tests.load_tests.load_test_constants import SERVER_TOKENS_LOG_FILE_NAME
from tests.load_tests.reporting.cross_run_comparison import CrossRunComparison
from tests.load_tests.reporting.token_log_writer import TokenLogWriter

# pylint: disable=protected-access


class TestCrossRunComparison(TestCase):
    """
    Unit tests for CrossRunComparison._extract_metrics(), _parse_validation_loops() and _value_or_dash().

    A missing, unreadable or malformed raw_results.json, or one that is not a JSON
    object, returns None (comparisons keep working) and reports the path and reason
    through SensitiveLogger. A server_tokens.log written by TokenLogWriter gives one
    validation-loop entry per request with at least LOOP_THRESHOLD LLM calls.
    A table cell shows "-" for a metric of 0 or less, else the value with its percent change.
    """

    @override
    def setUp(self) -> None:
        """
        Create a scratch directory removed again after each test.
        """
        self._dir: str = mkdtemp()
        self.addCleanup(rmtree, self._dir)

    def test_valid_file_returns_metrics(self) -> None:
        """
        A readable, well-formed file parses into metrics and logs nothing.
        """
        path: str = self._write(dumps({"config": {"agent": "hello_world", "num_requests": 3}}))

        with patch("tests.load_tests.reporting.cross_run_comparison.SensitiveLogger") as mock_cls:
            metrics: Optional[Dict[str, Any]] = CrossRunComparison._extract_metrics(path, "run-1")

        self.assertIsNotNone(metrics)
        self.assertEqual(metrics.get("agent"), "hello_world")
        mock_cls.assert_not_called()

    def test_missing_file_is_logged_and_returns_none(self) -> None:
        """
        A path that does not exist returns None and logs the path and reason.
        """
        missing_path: str = join(self._dir, "does_not_exist.json")

        reason: Union[OSError, ValueError, str] = self._assert_logged_none(missing_path)
        self.assertIsInstance(reason, FileNotFoundError)

    def test_malformed_json_is_logged_and_returns_none(self) -> None:
        """
        Invalid JSON content returns None and logs the path and reason.
        """
        path: str = self._write("{not valid json")

        reason: Union[OSError, ValueError, str] = self._assert_logged_none(path)
        self.assertIsInstance(reason, JSONDecodeError)

    def test_non_object_json_is_logged_and_returns_none(self) -> None:
        """
        Valid JSON that is a list, not an object, returns None and logs the path and reason.
        """
        path: str = self._write(dumps([1, 2]))

        reason: Union[OSError, ValueError, str] = self._assert_logged_none(path)
        self.assertIn("not a JSON object", reason)

    def test_unreadable_file_is_logged_and_returns_none(self) -> None:
        """
        A PermissionError while opening the file returns None and logs the path and reason.
        """
        path: str = self._write(dumps({"config": {}}))

        reason: Optional[Union[OSError, ValueError, str]] = None
        with patch("builtins.open", side_effect=PermissionError("permission denied")):
            reason = self._assert_logged_none(path)
        self.assertIsInstance(reason, PermissionError)

    def test_validation_loops_from_token_log_writer(self) -> None:
        """
        A server_tokens.log from TokenLogWriter gives one loop entry for a 12-call request and none for a 4-call one.
        """
        results: List[Dict[str, Any]] = [
            {
                "request_id": "request-1",
                "status": "CREATED",
                "elapsed": 30.0,
                "total_tokens": 1500,
                "prompt_tokens": 1000,
                "completion_tokens": 500,
                "llm_calls": 12,
                "model": "gpt-4o-mini",
                "reporting_agent": "hello_world",
            },
            {
                "request_id": "request-2",
                "status": "CREATED",
                "elapsed": 5.0,
                "total_tokens": 400,
                "prompt_tokens": 300,
                "completion_tokens": 100,
                "llm_calls": 4,
                "model": "gpt-4o-mini",
                "reporting_agent": "hello_world",
            },
        ]
        with self.assertLogs("tests.load_tests.reporting.token_log_writer", level="INFO"):
            TokenLogWriter.log_token_summary(results, output_dir=self._dir)

        log_path: str = join(self._dir, SERVER_TOKENS_LOG_FILE_NAME)
        loops: List[Dict[str, Any]] = CrossRunComparison._parse_validation_loops(log_path)

        self.assertEqual(1, len(loops), loops)
        loop_entry: Dict[str, Any] = loops[0]
        cost_dollars: float = loop_entry.get("cost_usd", -1.0)
        expected: Dict[str, Any] = {
            "request_id": "request-1",
            "llm_calls": 12,
            "retries": 8,
            "prompt_tokens": 1000,
            "completion_tokens": 500,
            "total_tokens": 1500,
            "model": "gpt-4o-mini",
            "cost_usd": cost_dollars,
        }
        self.assertEqual(expected, loop_entry)
        self.assertGreaterEqual(cost_dollars, 0.0)

    def test_missing_value_cell_is_dash(self) -> None:
        """
        A metric of 0 or less gives a plain "-" cell, with or without a percent change.
        """
        zero_cell: str = CrossRunComparison._value_or_dash(0.0, "0s", 12.0)
        negative_cell: str = CrossRunComparison._value_or_dash(-1.0, "-1s", None)

        self.assertEqual("-", zero_cell)
        self.assertEqual("-", negative_cell)

    def test_value_cell_shows_value_and_percent_change(self) -> None:
        """
        A metric above 0 gives its value with the percent change, or the value alone for the baseline run.
        """
        increase_cell: str = CrossRunComparison._value_or_dash(45.0, "45s", 12.0)
        decrease_cell: str = CrossRunComparison._value_or_dash(512.0, "512M", -20.4)
        baseline_cell: str = CrossRunComparison._value_or_dash(45.0, "45s", None)

        self.assertEqual("45s (+12%)", increase_cell)
        self.assertEqual("512M (-20%)", decrease_cell)
        self.assertEqual("45s", baseline_cell)

    def _write(self, contents: str) -> str:
        """
        Write a raw_results.json with the given contents.

        :param contents: Raw file contents
        :return: Path of the created file
        """
        path: str = join(self._dir, RAW_RESULTS_FILE_NAME)
        with open(path, "w", encoding="utf-8") as file_handle:
            file_handle.write(contents)
        return path

    def _assert_logged_none(self, path: str) -> Union[OSError, ValueError, str]:
        """
        Assert _extract_metrics(path, ...) returns None and logs the path via SensitiveLogger.

        :param path: raw_results.json path to extract metrics from
        :return: The logged reason: the exception, or a message when no exception was raised
        """
        with patch("tests.load_tests.reporting.cross_run_comparison.SensitiveLogger") as mock_cls:
            mock_logger: MagicMock = mock_cls.return_value
            metrics: Optional[Dict[str, Any]] = CrossRunComparison._extract_metrics(path, "run-1")

        self.assertIsNone(metrics)
        mock_logger.error.assert_called_once()
        logged_args: Tuple[Any, ...] = mock_logger.error.call_args.args
        self.assertIn(path, logged_args)
        reason: Union[OSError, ValueError, str] = logged_args[-1]
        return reason
