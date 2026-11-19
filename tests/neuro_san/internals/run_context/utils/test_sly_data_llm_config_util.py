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

    @staticmethod
    def get_byok_schema() -> Dict[str, Any]:
        """
        Get an llm_config schema where any one of three API keys is required and the API base is optional.

        :return: The llm_config schema dictionary
        """
        return {
            "type": "object",
            "properties": {
                "openai_api_key": {"type": "string"},
                "openai_api_base": {"type": "string"},
                "anthropic_api_key": {"type": "string"},
                "google_api_key": {"type": "string"},
            },
            "anyOf": [
                {"required": ["openai_api_key"]},
                {"required": ["anthropic_api_key"]},
                {"required": ["google_api_key"]},
            ]
        }

    def test_missing_optional_key_is_set_to_none(self) -> None:
        """
        A missing key that the schema declares but never requires is set to None and not reported.
        """
        config: Dict[str, Any] = {"openai_api_key": "sly_data", "openai_api_base": "sly_data"}
        sly_data: Dict[str, Any] = {"llm_config": {"openai_api_key": "sk-test"}}

        result: Dict[str, Any] | Set[str] = SlyDataLlmConfigUtil.replace_llm_config_with_sly_data(
            config, sly_data, self.get_byok_schema())

        self.assertIs(config, result)
        self.assertEqual("sk-test", result.get("openai_api_key"))
        self.assertIsNone(result.get("openai_api_base"))

    def test_missing_any_of_key_is_reported(self) -> None:
        """
        A missing anyOf key is reported when the client provided none of the alternatives.
        """
        config: Dict[str, Any] = {"openai_api_key": "sly_data", "openai_api_base": "sly_data"}
        sly_data: Dict[str, Any] = {"llm_config": {"openai_api_base": "https://gateway"}}

        result: Dict[str, Any] | Set[str] = SlyDataLlmConfigUtil.replace_llm_config_with_sly_data(
            config, sly_data, self.get_byok_schema())

        self.assertEqual({"openai_api_key"}, result)

    def test_key_absent_from_schema_is_reported(self) -> None:
        """
        A missing key that the schema does not declare is reported.
        """
        config: Dict[str, Any] = {"openai_organization": "sly_data"}

        result: Dict[str, Any] | Set[str] = SlyDataLlmConfigUtil.replace_llm_config_with_sly_data(
            config, {}, self.get_byok_schema())

        self.assertEqual({"openai_organization"}, result)

    def test_get_optional_keys(self) -> None:
        """
        Only properties that no top-level or combinator "required" list names are optional.
        """
        schema: Dict[str, Any] = self.get_byok_schema()
        schema["properties"]["openai_organization"] = {"type": "string"}
        schema["required"] = ["openai_organization"]

        self.assertEqual({"openai_api_base"}, SlyDataLlmConfigUtil.get_optional_keys(schema))
        self.assertEqual(set(), SlyDataLlmConfigUtil.get_optional_keys(None))

    def test_describe_missing_keys_without_schema(self) -> None:
        """
        Without a schema, every missing key is listed as an alternative on its own line.
        """
        message: str = SlyDataLlmConfigUtil.describe_missing_keys(["openai_api_key", "anthropic_api_key"])

        self.assertEqual("LLM operation for this agent requires at least one of the following set in "
                         "sly_data.llm_config:\n"
                         "    anthropic_api_key\n"
                         "    openai_api_key\n", message)

    def test_describe_missing_keys_with_any_of(self) -> None:
        """
        Missing keys from anyOf alternatives are described as one group, in schema order.
        """
        message: str = SlyDataLlmConfigUtil.describe_missing_keys(["anthropic_api_key", "openai_api_key"],
                                                                  self.get_byok_schema())

        self.assertEqual("LLM operation for this agent requires the following set in sly_data.llm_config:\n"
                         "    one of: openai_api_key, anthropic_api_key\n", message)

    def test_describe_missing_keys_with_required_and_undescribed(self) -> None:
        """
        Always-required keys and keys the schema does not mention get sections of their own.
        """
        schema: Dict[str, Any] = self.get_byok_schema()
        schema["allOf"] = [{"required": ["openai_organization"]}]

        message: str = SlyDataLlmConfigUtil.describe_missing_keys(
            ["openai_organization", "google_api_key", "azure_openai_api_key"], schema)

        self.assertEqual("LLM operation for this agent requires the following set in sly_data.llm_config:\n"
                         "    all of: openai_organization\n"
                         "    one of: google_api_key\n"
                         "    one of (not in the sly_data_schema): azure_openai_api_key\n", message)

    def test_key_excused_by_satisfied_any_of_is_skipped(self) -> None:
        """
        A missing anyOf key is not reported when the client provided another alternative,
        and the config comes back as an empty set so that it is skipped.
        """
        config: Dict[str, Any] = {"openai_api_key": "sly_data", "openai_api_base": "sly_data"}
        sly_data: Dict[str, Any] = {"llm_config": {"anthropic_api_key": "sk-ant"}}

        result: Dict[str, Any] | Set[str] = SlyDataLlmConfigUtil.replace_llm_config_with_sly_data(
            config, sly_data, self.get_byok_schema())

        self.assertEqual(set(), result)
        self.assertEqual("sly_data", config.get("openai_api_key"))

    def test_always_required_key_is_reported_alongside_excused_key(self) -> None:
        """
        A key the schema always requires is reported even when an anyOf alternative is satisfied.
        """
        schema: Dict[str, Any] = self.get_byok_schema()
        schema["properties"]["openai_organization"] = {"type": "string"}
        schema["required"] = ["openai_organization"]
        config: Dict[str, Any] = {"openai_api_key": "sly_data", "openai_organization": "sly_data"}
        sly_data: Dict[str, Any] = {"llm_config": {"anthropic_api_key": "sk-ant"}}

        result: Dict[str, Any] | Set[str] = SlyDataLlmConfigUtil.replace_llm_config_with_sly_data(
            config, sly_data, schema)

        self.assertEqual({"openai_organization"}, result)

    def test_get_excused_keys(self) -> None:
        """
        Every alternative of a satisfied group is excused; nothing is excused when no alternative is provided.
        """
        schema: Dict[str, Any] = self.get_byok_schema()

        excused: Set[str] = SlyDataLlmConfigUtil.get_excused_keys(schema, {"google_api_key": "g"})
        self.assertEqual({"openai_api_key", "anthropic_api_key", "google_api_key"}, excused)
        self.assertEqual(set(), SlyDataLlmConfigUtil.get_excused_keys(schema, {"openai_api_base": "b"}))
        self.assertEqual(set(), SlyDataLlmConfigUtil.get_excused_keys(None, {"google_api_key": "g"}))
