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

from io import BytesIO
from typing import Any
from typing import Dict
from typing import List
from typing import Set
from typing import Tuple
from unittest import TestCase

from leaf_common.serialization.format.hocon_serialization_format import HoconSerializationFormat

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

    # The BYOK llm_config example from the sly_data_schema design discussion, kept verbatim as HOCON.
    BYOK_LLM_CONFIG_HOCON: str = """
            # A BYOK llm_config_property to be inserted in an already existing sly_data_schema.
            # Note that with hocon we can only define values to be used later in substitution.
            "llm_config": {
                "type": "object",
                "properties": {
                    "openai_api_key": {
                        "type": "string",
                        "description": "The user's OpenAI API key"
                    },
                    "openai_api_base": {
                        "type": "string",
                        "description": "An optional OpenAI endpoint URL"
                    },
                    "anthropic_api_key": {
                        "type": "string",
                        "description": "The user's Anthropic API key"
                    },
                    "google_api_key": {
                        "type": "string",
                        "description": "The user's Google API key for use with Gemini models"
                    },
                },
                # Note that none of these properties are strictly required, as all are individually optional,
                # but at least one of these properties must be present, hence the "anyOf" below.
                # However, in a BYOK situation, we do always expect the llm_config property itself to be required
                # with at least one of these values present.
                "anyOf": [
                    { "required": ["openai_api_key"] },
                    { "required": ["anthropic_api_key"] },
                    { "required": ["google_api_key"] }
                ]
            }
"""

    @staticmethod
    def get_byok_schema() -> Dict[str, Any]:
        """
        Parse the BYOK example, where any one of three API keys is required and the API base is optional.

        :return: A fresh copy of the llm_config schema dictionary
        """
        hocon_format: HoconSerializationFormat = HoconSerializationFormat()
        parsed: Dict[str, Any] = hocon_format.to_object(BytesIO(TestSlyDataLlmConfigUtil.BYOK_LLM_CONFIG_HOCON
                                                                .encode("utf-8")))
        return parsed.get("llm_config")

    def test_byok_example_requires_any_one_key_and_never_the_base(self) -> None:
        """
        With the BYOK example schema, any one provider key is enough, openai_api_base is never
        reported, and a provider key is only reported when the client sent none of the three.
        """
        # Each case: the LLM's key, the sly_data.llm_config sent, and the expected result,
        # where None means the config is usable.
        cases: List[Tuple[str, Dict[str, Any], Set[str]]] = [
            ("openai_api_key", {"openai_api_key": "sk-openai"}, None),
            ("anthropic_api_key", {"anthropic_api_key": "sk-ant"}, None),
            ("google_api_key", {"google_api_key": "g-key"}, None),
            ("openai_api_key", {"openai_api_key": "sk-openai", "openai_api_base": "https://gw"}, None),
            ("openai_api_key", {"anthropic_api_key": "sk-ant"}, set()),
            ("google_api_key", {"openai_api_key": "sk-openai"}, set()),
            ("openai_api_key", {}, {"openai_api_key"}),
            ("openai_api_key", {"openai_api_base": "https://gw"}, {"openai_api_key"}),
            ("anthropic_api_key", {}, {"anthropic_api_key"}),
            # Blank strings count as not set, both for the LLM's own key and for the other alternatives.
            ("openai_api_key", {"openai_api_key": ""}, {"openai_api_key"}),
            ("openai_api_key", {"openai_api_key": "  \n"}, {"openai_api_key"}),
            ("openai_api_key", {"openai_api_key": "", "anthropic_api_key": "sk-ant"}, set()),
            ("openai_api_key", {"anthropic_api_key": " "}, {"openai_api_key"}),
            ("openai_api_key", {"openai_api_key": "sk-openai", "openai_api_base": ""}, None),
        ]

        # Loop through each case, with every LLM also asking for the optional API base.
        case: Tuple[str, Dict[str, Any], Set[str]] = None
        for case in cases:
            api_key: str = case[0]
            llm_config: Dict[str, Any] = case[1]
            expected: Set[str] = case[2]
            # The label is a string so that the subtest stays picklable under xdist.
            with self.subTest(case=str(case)):
                config: Dict[str, Any] = {api_key: "sly_data", "openai_api_base": "sly_data"}

                result: Dict[str, Any] | Set[str] = SlyDataLlmConfigUtil.replace_llm_config_with_sly_data(
                    config, {"llm_config": llm_config}, self.get_byok_schema())

                if expected is not None:
                    self.assertEqual(expected, result)
                    continue
                self.assertIs(config, result)
                self.assertEqual(llm_config.get(api_key), result.get(api_key))
                # A blank API base is not set, so it becomes None like a missing one.
                expected_base: str = llm_config.get("openai_api_base") or None
                self.assertEqual(expected_base, result.get("openai_api_base"))

        message: str = SlyDataLlmConfigUtil.describe_missing_keys(
            ["google_api_key", "anthropic_api_key", "openai_api_key"], self.get_byok_schema())
        self.assertEqual("LLM operation for this agent requires the following set in sly_data.llm_config:\n"
                         "    one of: openai_api_key, anthropic_api_key, google_api_key\n", message)

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
        self.assertEqual(set(), SlyDataLlmConfigUtil.get_excused_keys(schema, {"google_api_key": "  "}))

    def test_get_provided_value(self) -> None:
        """
        Strings come back stripped, blank strings and missing keys come back as None,
        and other values come back unchanged.
        """
        provided: Dict[str, Any] = {"key": " sk-test\t", "empty": "", "blank": " \n ", "number": 0, "none": None}

        self.assertEqual("sk-test", SlyDataLlmConfigUtil.get_provided_value(provided, "key"))
        self.assertIsNone(SlyDataLlmConfigUtil.get_provided_value(provided, "empty"))
        self.assertIsNone(SlyDataLlmConfigUtil.get_provided_value(provided, "blank"))
        self.assertEqual(0, SlyDataLlmConfigUtil.get_provided_value(provided, "number"))
        self.assertIsNone(SlyDataLlmConfigUtil.get_provided_value(provided, "none"))
        self.assertIsNone(SlyDataLlmConfigUtil.get_provided_value(provided, "absent"))
