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
import shutil
import tempfile
from typing import Any
from typing import Dict
from typing import Optional
from typing import Tuple
from typing import Union
from unittest import TestCase
from unittest.mock import MagicMock
from unittest.mock import patch

from typing_extensions import override

from tests.load_tests.reporting.cross_run_comparison import CrossRunComparison

# pylint: disable=protected-access


class TestCrossRunComparison(TestCase):
    """
    Unit tests for CrossRunComparison._extract_metrics().

    A missing, unreadable or malformed raw_results.json, or one that is not a JSON
    object, returns None (comparisons keep working) and reports the path and reason
    through SensitiveLogger.
    """

    @override
    def setUp(self) -> None:
        """
        Create a scratch directory removed again after each test.
        """
        self._dir: str = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self._dir)

    def test_valid_file_returns_metrics(self) -> None:
        """
        A readable, well-formed file parses into metrics and logs nothing.
        """
        path: str = self._write(json.dumps({"config": {"agent": "hello_world", "num_requests": 3}}))

        with patch("tests.load_tests.reporting.cross_run_comparison.SensitiveLogger") as mock_cls:
            metrics: Optional[Dict[str, Any]] = CrossRunComparison._extract_metrics(path, "run-1")

        self.assertIsNotNone(metrics)
        self.assertEqual(metrics.get("agent"), "hello_world")
        mock_cls.assert_not_called()

    def test_missing_file_is_logged_and_returns_none(self) -> None:
        """
        A path that does not exist returns None and logs the path and reason.
        """
        missing_path: str = os.path.join(self._dir, "does_not_exist.json")

        reason: Union[OSError, ValueError, str] = self._assert_logged_none(missing_path)
        self.assertIsInstance(reason, FileNotFoundError)

    def test_malformed_json_is_logged_and_returns_none(self) -> None:
        """
        Invalid JSON content returns None and logs the path and reason.
        """
        path: str = self._write("{not valid json")

        reason: Union[OSError, ValueError, str] = self._assert_logged_none(path)
        self.assertIsInstance(reason, json.JSONDecodeError)

    def test_non_object_json_is_logged_and_returns_none(self) -> None:
        """
        Valid JSON that is a list, not an object, returns None and logs the path and reason.
        """
        path: str = self._write(json.dumps([1, 2]))

        reason: Union[OSError, ValueError, str] = self._assert_logged_none(path)
        self.assertIn("not a JSON object", reason)

    def test_unreadable_file_is_logged_and_returns_none(self) -> None:
        """
        A PermissionError while opening the file returns None and logs the path and reason.
        """
        path: str = self._write(json.dumps({"config": {}}))

        reason: Optional[Union[OSError, ValueError, str]] = None
        with patch("builtins.open", side_effect=PermissionError("permission denied")):
            reason = self._assert_logged_none(path)
        self.assertIsInstance(reason, PermissionError)

    def _write(self, contents: str) -> str:
        """
        Write a raw_results.json with the given contents.

        :param contents: Raw file contents
        :return: Path of the created file
        """
        path: str = os.path.join(self._dir, "raw_results.json")
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
