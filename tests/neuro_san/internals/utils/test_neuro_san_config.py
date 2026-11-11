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
import os

from typing import Any

from unittest import TestCase
from unittest.mock import patch

from typing_extensions import override

from neuro_san.internals.utils.neuro_san_config import NeuroSanConfig


class TestNeuroSanConfig(TestCase):
    """
    Unit tests for NeuroSanConfig: reading AGENT_* settings with their defaults.
    """

    # A key with a non-None default, and one with a None default
    DEFAULTED_KEY: str = "internals.hardening.AGENT_PROTECT_ORIGINAL_COPY"
    NONE_DEFAULT_KEY: str = "internals.tools.AGENT_TOOL_PATH"

    @override
    def setUp(self) -> None:
        """
        Isolates the environment for each test and reloads NeuroSanConfig once it is restored.
        """
        # Cleanups run last-in first-out, so this reload sees the restored environment.
        self.addCleanup(NeuroSanConfig.reset_for_testing)
        env_patcher: Any = patch.dict(os.environ)
        env_patcher.start()
        self.addCleanup(env_patcher.stop)

    @staticmethod
    def set_env(name: str, value: str) -> None:
        """
        Sets an environment variable, which NeuroSanConfig reads on each lookup.

        :param name: The environment variable name
        :param value: The value to set
        """
        os.environ[name] = value

    @staticmethod
    def unset_env(name: str) -> None:
        """
        Removes an environment variable and reloads NeuroSanConfig to see it.

        :param name: The environment variable name
        """
        os.environ.pop(name, None)
        NeuroSanConfig.reset_for_testing()

    def test_unset_variable_uses_default(self) -> None:
        """
        With the variable unset, get() and get_non_empty() both return the default.
        """
        self.unset_env("AGENT_PROTECT_ORIGINAL_COPY")
        self.assertEqual("true", NeuroSanConfig.get(TestNeuroSanConfig.DEFAULTED_KEY))
        self.assertEqual("true", NeuroSanConfig.get_non_empty(TestNeuroSanConfig.DEFAULTED_KEY))

        self.unset_env("AGENT_TOOL_PATH")
        self.assertIsNone(NeuroSanConfig.get(TestNeuroSanConfig.NONE_DEFAULT_KEY))
        self.assertIsNone(NeuroSanConfig.get_non_empty(TestNeuroSanConfig.NONE_DEFAULT_KEY))

    def test_set_variable_overrides_default(self) -> None:
        """
        A set variable wins over the default for both get() and get_non_empty().
        """
        self.set_env("AGENT_PROTECT_ORIGINAL_COPY", "false")
        self.assertEqual("false", NeuroSanConfig.get(TestNeuroSanConfig.DEFAULTED_KEY))
        self.assertEqual("false", NeuroSanConfig.get_non_empty(TestNeuroSanConfig.DEFAULTED_KEY))

    def test_empty_variable(self) -> None:
        """
        get() keeps an empty value, while get_non_empty() replaces it with the default.
        """
        self.set_env("AGENT_PROTECT_ORIGINAL_COPY", "")
        self.assertEqual("", NeuroSanConfig.get(TestNeuroSanConfig.DEFAULTED_KEY))
        self.assertEqual("true", NeuroSanConfig.get_non_empty(TestNeuroSanConfig.DEFAULTED_KEY))

        self.set_env("AGENT_TOOL_PATH", "")
        self.assertEqual("", NeuroSanConfig.get(TestNeuroSanConfig.NONE_DEFAULT_KEY))
        self.assertIsNone(NeuroSanConfig.get_non_empty(TestNeuroSanConfig.NONE_DEFAULT_KEY))

    def test_get_bool(self) -> None:
        """
        get_bool() converts the value, and replaces an empty value with the default.
        """
        self.unset_env("AGENT_PROTECT_ORIGINAL_COPY")
        self.assertTrue(NeuroSanConfig.get_bool(TestNeuroSanConfig.DEFAULTED_KEY))

        self.set_env("AGENT_PROTECT_ORIGINAL_COPY", "false")
        self.assertFalse(NeuroSanConfig.get_bool(TestNeuroSanConfig.DEFAULTED_KEY))

        self.set_env("AGENT_PROTECT_ORIGINAL_COPY", "")
        self.assertTrue(NeuroSanConfig.get_bool(TestNeuroSanConfig.DEFAULTED_KEY))
