
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
from typing import Any
from typing import List
from typing import Optional

import os

from unittest import TestCase
from unittest.mock import patch

from typing_extensions import override

from neuro_san.session.session_util import SessionUtil


class TestSessionUtil(TestCase):
    """
    Unit tests for SessionUtil: how MAX_AGENTS_FROM_EXTERNAL_SERVER is read and applied to a listing.
    """

    AGENTS: List[str] = ["a", "b", "c", "d", "e"]
    LOGGER_NAME: str = SessionUtil.__name__

    @override
    def setUp(self) -> None:
        """
        Starts each test with MAX_AGENTS_FROM_EXTERNAL_SERVER unset, whatever the shell exports.
        """
        # patch.dict restores all of os.environ on cleanup, even if the test fails, so variables can be
        # removed or set freely here and in each test.
        env_patcher: Any = patch.dict(os.environ)
        env_patcher.start()
        self.addCleanup(env_patcher.stop)
        os.environ.pop(SessionUtil.MAX_AGENTS_ENV_VAR, None)

    @staticmethod
    def set_limit(value: Optional[str]) -> None:
        """
        Sets or removes MAX_AGENTS_FROM_EXTERNAL_SERVER for the current test.

        :param value: The value to set, or None to remove the variable
        """
        if value is None:
            os.environ.pop(SessionUtil.MAX_AGENTS_ENV_VAR, None)
        else:
            os.environ[SessionUtil.MAX_AGENTS_ENV_VAR] = value

    def test_unset_means_no_limit(self) -> None:
        """
        With the variable unset, the listing comes back untouched and nothing is logged.
        """
        self.set_limit(None)
        self.assertEqual(0, SessionUtil.get_max_agents())
        with self.assertNoLogs(self.LOGGER_NAME):
            self.assertIs(self.AGENTS, SessionUtil.limit_agents_list(self.AGENTS))

    def test_zero_negative_and_blank_mean_no_limit(self) -> None:
        """
        "0" (the Dockerfile default), negatives and blank strings mean no limit; nothing is logged.
        """
        for value in ["0", "-1", "-999", "", "  "]:
            with self.subTest(value=value):
                self.set_limit(value)
                self.assertEqual(0, SessionUtil.get_max_agents())
                with self.assertNoLogs(self.LOGGER_NAME):
                    self.assertIs(self.AGENTS, SessionUtil.limit_agents_list(self.AGENTS))

    def test_positive_limit_truncates_and_warns(self) -> None:
        """
        A positive limit keeps the first N entries and logs one warning that names the variable.
        """
        self.set_limit("3")
        self.assertEqual(3, SessionUtil.get_max_agents())
        with self.assertLogs(self.LOGGER_NAME, level="WARNING") as logs:
            limited: List[str] = SessionUtil.limit_agents_list(self.AGENTS)
        self.assertEqual(["a", "b", "c"], limited)
        self.assertEqual(1, len(logs.output))
        self.assertIn(SessionUtil.MAX_AGENTS_ENV_VAR, logs.output[0])

    def test_limit_not_reached_returns_list_unchanged(self) -> None:
        """
        A limit at or above the list length changes nothing and logs nothing.
        """
        for value in ["5", "6", "100"]:
            with self.subTest(value=value):
                self.set_limit(value)
                with self.assertNoLogs(self.LOGGER_NAME):
                    self.assertIs(self.AGENTS, SessionUtil.limit_agents_list(self.AGENTS))

    def test_integer_parsing_tolerates_whitespace_and_sign(self) -> None:
        """
        Values with surrounding whitespace or a leading "+" still parse as a limit.
        """
        for value in [" 2 ", "+2", "2\n"]:
            with self.subTest(value=value):
                self.set_limit(value)
                self.assertEqual(2, SessionUtil.get_max_agents())

    def test_non_integer_is_ignored_with_warning(self) -> None:
        """
        A non-integer value means no limit; the warning names the variable and includes the value.
        """
        for value in ["abc", "2.5", "5o"]:
            with self.subTest(value=value):
                self.set_limit(value)
                with self.assertLogs(self.LOGGER_NAME, level="WARNING") as logs:
                    self.assertEqual(0, SessionUtil.get_max_agents())
                self.assertEqual(1, len(logs.output))
                self.assertIn(SessionUtil.MAX_AGENTS_ENV_VAR, logs.output[0])
                self.assertIn(value, logs.output[0])

    def test_non_list_input_is_returned_unchanged(self) -> None:
        """
        Anything that is not a list (None, a dict, a string) is returned unchanged even when a limit is set.
        """
        self.set_limit("2")
        for payload in [None, {"a": 1, "b": 2, "c": 3}, "abcd"]:
            with self.subTest(payload=payload):
                self.assertIs(payload, SessionUtil.limit_agents_list(payload))
