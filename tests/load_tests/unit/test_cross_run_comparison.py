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
from typing import Any
from typing import Dict
from typing import Optional
from unittest import TestCase
from unittest.mock import MagicMock
from unittest.mock import patch

from typing_extensions import override

from tests.load_tests.reporting.cross_run_comparison import CrossRunComparison

# pylint: disable=protected-access


class TestCrossRunComparison(TestCase):
    """
    Unit tests for CrossRunComparison._extract_metrics().

    A missing, unreadable or malformed raw_results.json must still return None
    (comparisons keep working), but the failure now has to be reported through
    SensitiveLogger instead of disappearing silently.
    """

    @override
    def setUp(self) -> None:
        """
        Create a scratch directory removed again after each test.

        """
        self._dir: str = tempfile.mkdtemp()
        self.addCleanup(self._remove_dir)

    def _remove_dir(self) -> None:
        """Remove the scratch directory and anything left in it."""
        for name in os.listdir(self._dir):
            os.unlink(os.path.join(self._dir, name))
        os.rmdir(self._dir)

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

    def test_valid_file_returns_metrics(self) -> None:
        """
        A readable, well-formed file still parses into metrics, unlogged.

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

        self._assert_logged_none(missing_path)

    def test_malformed_json_is_logged_and_returns_none(self) -> None:
        """
        Invalid JSON content returns None and logs the path and reason.

        """
        path: str = self._write("{not valid json")

        self._assert_logged_none(path)

    def test_unreadable_file_is_logged_and_returns_none(self) -> None:
        """
        An OSError while opening the file returns None and logs the path and reason.

        """
        path: str = self._write(json.dumps({"config": {}}))

        with patch("tests.load_tests.reporting.cross_run_comparison.SensitiveLogger") as mock_cls:
            mock_logger: MagicMock = mock_cls.return_value
            with patch("builtins.open", side_effect=OSError("permission denied")):
                metrics: Optional[Dict[str, Any]] = CrossRunComparison._extract_metrics(path, "run-1")

        self.assertIsNone(metrics)
        mock_logger.error.assert_called_once()
        logged_args: tuple = mock_logger.error.call_args.args
        self.assertIn(path, logged_args)

    def _assert_logged_none(self, path: str) -> None:
        """
        Assert _extract_metrics(path, ...) returns None and logs the path via SensitiveLogger.

        :param path: raw_results.json path to extract metrics from

        """
        with patch("tests.load_tests.reporting.cross_run_comparison.SensitiveLogger") as mock_cls:
            mock_logger: MagicMock = mock_cls.return_value
            metrics: Optional[Dict[str, Any]] = CrossRunComparison._extract_metrics(path, "run-1")

        self.assertIsNone(metrics)
        mock_logger.error.assert_called_once()
        logged_args: tuple = mock_logger.error.call_args.args
        self.assertIn(path, logged_args)
