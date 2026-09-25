
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
    Unit tests for SessionUtil's MAX_AGENTS_FROM_EXTERNAL_SERVER policy: which values of the
    variable mean "no limit", which truncate a server listing, and that both a truncation and
    an unusable value are logged rather than silently applied or silently ignored.
    """

    AGENTS: List[str] = ["a", "b", "c", "d", "e"]
    LOGGER_NAME: str = SessionUtil.__name__

    @override
    def setUp(self) -> None:
        """
        Pins the environment so that a MAX_AGENTS_FROM_EXTERNAL_SERVER exported in the
        developer's shell cannot change what these tests see.
        """
        # patch.dict snapshots os.environ on start() and restores the whole mapping on stop(),
        # so the variable can simply be removed here and any per-test value set later; both
        # are undone by the cleanup, which runs even if the test raises.
        env_patcher: Any = patch.dict(os.environ)
        env_patcher.start()
        self.addCleanup(env_patcher.stop)
        os.environ.pop(SessionUtil.MAX_AGENTS_ENV_VAR, None)

    @staticmethod
    def set_limit(value: Optional[str]) -> None:
        """
        Sets or removes MAX_AGENTS_FROM_EXTERNAL_SERVER for the rest of the current test.

        :param value: The string to export, or None to leave the variable unset
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
        "0" (the Dockerfile default), negative numbers and an empty or blank string all mean
        no limit, and none of them is worth a warning.
        """
        for value in ["0", "-1", "-999", "", "  "]:
            with self.subTest(value=value):
                self.set_limit(value)
                self.assertEqual(0, SessionUtil.get_max_agents())
                with self.assertNoLogs(self.LOGGER_NAME):
                    self.assertIs(self.AGENTS, SessionUtil.limit_agents_list(self.AGENTS))

    def test_positive_limit_truncates_and_warns(self) -> None:
        """
        A positive limit keeps the first N entries and logs one warning naming the variable,
        so that an agent missing from the result can be traced back to the setting.
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
        A limit the listing already fits within changes nothing and logs nothing.
        """
        for value in ["5", "6", "100"]:
            with self.subTest(value=value):
                self.set_limit(value)
                with self.assertNoLogs(self.LOGGER_NAME):
                    self.assertIs(self.AGENTS, SessionUtil.limit_agents_list(self.AGENTS))

    def test_integer_parsing_tolerates_whitespace_and_sign(self) -> None:
        """
        int() accepts surrounding whitespace and an explicit plus sign, so those spellings
        are limits, not typos.
        """
        for value in [" 2 ", "+2", "2\n"]:
            with self.subTest(value=value):
                self.set_limit(value)
                self.assertEqual(2, SessionUtil.get_max_agents())

    def test_non_integer_is_ignored_with_warning(self) -> None:
        """
        A value int() cannot parse means no limit, but is logged with the offending value so
        the typo does not pass for a working limit.
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
        A malformed payload (None, a dict or a string where a list was expected) is handed back
        as-is even when a limit is set, rather than raising from a slice in here.
        """
        self.set_limit("2")
        for payload in [None, {"a": 1, "b": 2, "c": 3}, "abcd"]:
            with self.subTest(payload=payload):
                self.assertIs(payload, SessionUtil.limit_agents_list(payload))
