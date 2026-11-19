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
from typing import Dict
from typing import Set
from unittest import TestCase

from neuro_san.internals.run_context.utils.sly_data_llm_config_util import SlyDataLlmConfigUtil


class TestSlyDataLlmConfigUtil(TestCase):
    """
    Test cases for SlyDataLlmConfigUtil.replace_llm_config_with_sly_data().
    """

    def test_replaces_sly_data_value_and_strips_whitespace(self) -> None:
        """
        A "sly_data" config value takes the stripped value of the same key in sly_data.llm_config.
        """
        config: Dict[str, Any] = {"model_name": "gpt-4o", "openai_api_key": "sly_data"}
        sly_data: Dict[str, Any] = {"llm_config": {"openai_api_key": "  sk-test \n"}}

        result: Dict[str, Any] | Set[str] = SlyDataLlmConfigUtil.replace_llm_config_with_sly_data(config, sly_data)

        self.assertIs(config, result)
        self.assertEqual("sk-test", result.get("openai_api_key"))
        self.assertEqual("gpt-4o", result.get("model_name"))

    def test_sly_data_marker_is_case_insensitive(self) -> None:
        """
        The "sly_data" marker matches regardless of case.
        """
        config: Dict[str, Any] = {"openai_api_key": "SLY_DATA"}
        sly_data: Dict[str, Any] = {"llm_config": {"openai_api_key": "sk-test"}}

        result: Dict[str, Any] | Set[str] = SlyDataLlmConfigUtil.replace_llm_config_with_sly_data(config, sly_data)

        self.assertEqual("sk-test", result.get("openai_api_key"))

    def test_non_string_value_is_used_as_is(self) -> None:
        """
        A non-string value from sly_data.llm_config replaces the marker without stripping.
        """
        config: Dict[str, Any] = {"temperature": "sly_data"}
        sly_data: Dict[str, Any] = {"llm_config": {"temperature": 0.5}}

        result: Dict[str, Any] | Set[str] = SlyDataLlmConfigUtil.replace_llm_config_with_sly_data(config, sly_data)

        self.assertEqual(0.5, result.get("temperature"))

    def test_missing_keys_are_reported_as_a_set(self) -> None:
        """
        Every "sly_data" key without a value in sly_data.llm_config is reported in the returned set.
        """
        config: Dict[str, Any] = {"openai_api_key": "sly_data", "openai_organization": "sly_data"}
        sly_data: Dict[str, Any] = {"llm_config": {"openai_organization": "org"}}

        result: Dict[str, Any] | Set[str] = SlyDataLlmConfigUtil.replace_llm_config_with_sly_data(config, sly_data)

        self.assertEqual({"openai_api_key"}, result)

    def test_none_sly_data_reports_every_marked_key(self) -> None:
        """
        With no sly_data at all, every "sly_data" key is reported missing.
        """
        config: Dict[str, Any] = {"openai_api_key": "sly_data", "model_name": "gpt-4o"}

        result: Dict[str, Any] | Set[str] = SlyDataLlmConfigUtil.replace_llm_config_with_sly_data(config, None)

        self.assertEqual({"openai_api_key"}, result)

    def test_config_without_markers_is_returned_unchanged(self) -> None:
        """
        A config with no "sly_data" values comes back as the same, unchanged dictionary.
        """
        config: Dict[str, Any] = {"model_name": "gpt-4o", "temperature": 0.1}
        expected: Dict[str, Any] = dict(config)

        result: Dict[str, Any] | Set[str] = SlyDataLlmConfigUtil.replace_llm_config_with_sly_data(config, {})

        self.assertIs(config, result)
        self.assertEqual(expected, result)
