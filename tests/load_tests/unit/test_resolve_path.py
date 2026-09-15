
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
from unittest import TestCase

from tests.load_tests.config import HISTORY_FILE_NAME
from tests.load_tests.reporting.trend_history import TrendHistory


# pylint: disable=protected-access
class TestResolvePath(TestCase):
    """
    Unit tests for TrendHistory._resolve_path().

    --trend accepts either the history file or the output directory
    holding it, because both are printed at the end of a run.
    """

    def setUp(self):
        """Create a scratch directory removed again after each test."""
        self._dir = tempfile.mkdtemp()
        self.addCleanup(self._remove_dir)

    def _remove_dir(self) -> None:
        """Remove the scratch directory and anything left in it."""
        for name in os.listdir(self._dir):
            os.unlink(os.path.join(self._dir, name))
        os.rmdir(self._dir)

    def _create_history(self) -> str:
        """Create a default-named history file in the scratch directory."""
        path = os.path.join(self._dir, HISTORY_FILE_NAME)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(json.dumps({"agent": "one"}) + "\n")
        return path

    def test_a_file_path_is_used_directly(self):
        """Passing the history file itself resolves to that file."""
        path = self._create_history()

        self.assertEqual(TrendHistory(path)._resolve_path(), path)

    def test_a_directory_resolves_to_its_history_file(self):
        """Passing the output directory finds history.jsonl inside it."""
        path = self._create_history()

        self.assertEqual(TrendHistory(self._dir)._resolve_path(), path)

    def test_missing_history_resolves_to_none(self):
        """A directory with no history file resolves to None."""
        self.assertIsNone(TrendHistory(self._dir)._resolve_path())
