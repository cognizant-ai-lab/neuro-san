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
from typing import Dict

from unittest import TestCase
from unittest.mock import patch

from typing_extensions import override

from leaf_common.config.config_filter import ConfigFilter

from neuro_san.internals.utils.environment_config_filter import EnvironmentConfigFilter


class TestEnvironmentConfigFilter(TestCase):
    """
    Unit tests for EnvironmentConfigFilter: replacing the leaf defaults of a nested
    config dictionary with the values of the environment variables they are keyed by.
    """

    ENV_VAR: str = "TEST_ENVIRONMENT_CONFIG_FILTER_VAR"

    @override
    def setUp(self) -> None:
        """
        Creates the filter under test and isolates the environment for each test.
        """
        self.config_filter: ConfigFilter = EnvironmentConfigFilter()

        # patch.dict restores all of os.environ on cleanup, even if the test fails.
        env_patcher: Any = patch.dict(os.environ)
        env_patcher.start()
        self.addCleanup(env_patcher.stop)
        os.environ.pop(TestEnvironmentConfigFilter.ENV_VAR, None)

    def make_config(self, default: Any) -> Dict[str, Any]:
        """
        Builds a nested config with a single leaf keyed by the test env var.

        :param default: The default value for the leaf
        :return: The nested config dictionary
        """
        return {"category": {"group": {TestEnvironmentConfigFilter.ENV_VAR: default}}}

    def get_leaf(self, config: Dict[str, Any]) -> Any:
        """
        Gets the single leaf value from a config built by make_config().

        :param config: The config dictionary to read
        :return: The leaf value
        """
        return config.get("category").get("group").get(TestEnvironmentConfigFilter.ENV_VAR)

    def test_absent_variable_uses_default(self) -> None:
        """
        An unset variable takes the default, including a None default.
        """
        filtered: Dict[str, Any] = self.config_filter.filter_config(self.make_config("fallback"))
        self.assertEqual("fallback", self.get_leaf(filtered))

        filtered = self.config_filter.filter_config(self.make_config(None))
        self.assertIsNone(self.get_leaf(filtered))

    def test_set_variable_overrides_default(self) -> None:
        """
        A set variable replaces the default.
        """
        os.environ[TestEnvironmentConfigFilter.ENV_VAR] = "from_env"
        filtered: Dict[str, Any] = self.config_filter.filter_config(self.make_config("fallback"))
        self.assertEqual("from_env", self.get_leaf(filtered))

    def test_empty_variable_is_preserved(self) -> None:
        """
        A variable set to an empty string keeps the empty value instead of taking the default,
        so presence-based settings and explicit "disable" values still work.
        """
        os.environ[TestEnvironmentConfigFilter.ENV_VAR] = ""
        filtered: Dict[str, Any] = self.config_filter.filter_config(self.make_config("fallback"))
        self.assertEqual("", self.get_leaf(filtered))

        filtered = self.config_filter.filter_config(self.make_config(None))
        self.assertEqual("", self.get_leaf(filtered))

    def test_basis_config_is_not_modified(self) -> None:
        """
        Filtering returns a new dictionary and leaves the basis config untouched.
        """
        os.environ[TestEnvironmentConfigFilter.ENV_VAR] = "from_env"
        basis: Dict[str, Any] = self.make_config("fallback")
        self.config_filter.filter_config(basis)
        self.assertEqual("fallback", self.get_leaf(basis))
