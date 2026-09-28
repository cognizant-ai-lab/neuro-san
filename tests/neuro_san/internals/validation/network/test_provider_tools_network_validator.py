
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
import tempfile

from copy import deepcopy
from typing import Any
from typing import Dict
from typing import List

from unittest import TestCase
from unittest.mock import patch

from typing_extensions import override

from leaf_common.validation.dictionary_validator import DictionaryValidator

from neuro_san.internals.validation.network.provider_tools_network_validator import ProviderToolsNetworkValidator

from tests.neuro_san.internals.validation.network.abstract_network_validator_test import AbstractNetworkValidatorTest


# The rule matrix (shape, near-miss, fallbacks, Gemini, loading) legitimately needs more than 20 cases.
# pylint: disable=too-many-public-methods
class TestProviderToolsNetworkValidator(TestCase, AbstractNetworkValidatorTest):
    """
    Unit tests for ProviderToolsNetworkValidator class.

    Every test starts from the filtered hello_world.hocon: front man "announcer"
    (tools ["synonymizer"]) and leaf "synonymizer" (no tools), both inheriting the
    network-level llm_config. The inherited test_valid() covers the unchanged network.
    """

    # A Gemini built-in tool entry.
    GOOGLE_SEARCH: Dict[str, Any] = {"google_search": {}}

    # A second Gemini built-in tool entry.
    CODE_EXECUTION: Dict[str, Any] = {"code_execution": {}}

    # An OpenAI built-in tool entry.
    WEB_SEARCH: Dict[str, Any] = {"type": "web_search"}

    # A Gemini model that llm_info knows.
    GEMINI_MODEL: str = "gemini-2.5-flash"

    # A coded tool, which never builds a model, naming a downstream agent the coded-tool way.
    CODED_TOOL: Dict[str, Any] = {
        "name": "coded",
        "class": "my_pkg.my_module.MyTool",
        "function": {"description": "A coded tool"},
        "args": {"tools": {"researcher": "synonymizer"}},
    }

    # A toolbox tool, which never builds a model either.
    TOOLBOX_TOOL: Dict[str, Any] = {
        "name": "tb",
        "toolbox": "website_search",
    }

    @override
    def create_validator(self) -> DictionaryValidator:
        """
        Creates an instance of the validator

        :return: A ProviderToolsNetworkValidator
        """
        return ProviderToolsNetworkValidator()

    @staticmethod
    def _network_llm_config(config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Reads the network-level llm_config of a restored config.

        :param config: The network config
        :return: Its top-level llm_config dictionary
        """
        return config.get("llm_config")

    @staticmethod
    def _with_network_llm_config(config: Dict[str, Any], llm_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Replaces the network-level llm_config and drops the copies the agents inherited.

        restore() hands back an already-filtered config in which every agent carries a
        copy of the network-level llm_config. Dropping those copies lets the validator's
        own filtering pass re-inherit the new network-level value, which is what a raw
        hocon with only a network-level llm_config looks like after filtering.

        :param config: The restored network config to modify in place
        :param llm_config: The new network-level llm_config
        :return: The same config, for chaining
        """
        config["llm_config"] = llm_config
        for agent in config.get("tools"):
            agent.pop("llm_config", None)
        return config

    @staticmethod
    def _agent(config: Dict[str, Any], name: str) -> Dict[str, Any]:
        """
        Finds one agent spec by name.

        :param config: The network config
        :param name: The agent name
        :return: The agent spec dictionary
        :raises KeyError: if no agent has that name
        """
        for agent in config.get("tools"):
            if agent.get("name") == name:
                return agent
        raise KeyError(name)

    def _add_non_llm_tools(self, config: Dict[str, Any]) -> None:
        """
        Adds a coded tool and a toolbox tool to the network and makes the announcer call them.

        :param config: The restored network config to modify in place
        """
        tools: List[Dict[str, Any]] = config.get("tools")
        tools.append(deepcopy(self.CODED_TOOL))
        tools.append(deepcopy(self.TOOLBOX_TOOL))
        announcer_tools: List[str] = self._agent(config, "announcer").get("tools")
        announcer_tools.append("coded")
        announcer_tools.append("tb")

    def _write_llm_info_file(self, hocon_text: str) -> str:
        """
        Writes a user llm_info_file for one test and schedules its removal.

        :param hocon_text: The hocon text of the file
        :return: The path to the file
        """
        # delete=False because the restorer opens the file by path after this handle is closed.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".hocon", delete=False) as hocon_file:
            hocon_file.write(hocon_text)
            hocon_path: str = hocon_file.name
        self.addCleanup(os.remove, hocon_path)
        return hocon_path

    def _gemini_network_with_llm_info_file(self, config: Dict[str, Any], llm_info_file: str) -> None:
        """
        Points the network at an llm_info_file and gives it a Gemini list that needs it, plus one shape error.

        The announcer inherits the Gemini list, so llm_info has to be loaded to judge it;
        the synonymizer's string provider_tools is a shape error that needs no llm_info,
        so it proves the class-independent checks still ran.

        :param config: The restored network config to modify in place
        :param llm_info_file: The value for the network's llm_info_file key
        """
        config["llm_info_file"] = llm_info_file
        self._with_network_llm_config(config, {"model_name": self.GEMINI_MODEL,
                                               "provider_tools": [self.GOOGLE_SEARCH]})
        self._agent(config, "synonymizer")["llm_config"] = {"provider_tools": "oops"}

    def _assert_only_synonymizer_shape_error(self, validator: DictionaryValidator, config: Dict[str, Any]) -> None:
        """
        Validates a config set up by _gemini_network_with_llm_info_file() whose llm_info cannot load.

        :param validator: The validator under test
        :param config: The network config
        """
        with self.assertLogs(ProviderToolsNetworkValidator.__name__, level="WARNING") as logs:
            errors: List[str] = validator.validate(config)

        self.assertEqual(1, len(errors), str(errors))
        self.assertIn("synonymizer 'llm_config.provider_tools' must be a list, got str.", errors[0])

        # The load failure itself must be reported, not swallowed.
        load_warnings: List[str] = []
        for line in logs.output:
            if "could not load llm_info" in line:
                load_warnings.append(line)
        self.assertEqual(1, len(load_warnings), str(logs.output))

    def test_valid_openai_list_at_network_level(self) -> None:
        """
        A well-formed OpenAI provider_tools list on the network is accepted with no errors.
        """
        validator: DictionaryValidator = self.create_validator()
        config: Dict[str, Any] = self.restore("hello_world.hocon")
        self._with_network_llm_config(config, {"model_name": "gpt-4.1", "provider_tools": [self.WEB_SEARCH]})

        errors: List[str] = validator.validate(config)
        self.assertEqual(0, len(errors), str(errors))

    def test_provider_tools_not_a_list(self) -> None:
        """
        A string provider_tools is reported exactly once, under the network label, not once per agent.
        """
        validator: DictionaryValidator = self.create_validator()
        config: Dict[str, Any] = self.restore("hello_world.hocon")
        self._network_llm_config(config)["provider_tools"] = "web_search"

        errors: List[str] = validator.validate(config)
        self.assertEqual(1, len(errors), str(errors))
        self.assertIn("network 'llm_config.provider_tools' must be a list, got str.", errors[0])

    def test_provider_tools_element_not_a_dict(self) -> None:
        """
        A non-dict element is reported with its index.
        """
        validator: DictionaryValidator = self.create_validator()
        config: Dict[str, Any] = self.restore("hello_world.hocon")
        self._network_llm_config(config)["provider_tools"] = [self.WEB_SEARCH, "code_interpreter"]

        errors: List[str] = validator.validate(config)
        self.assertEqual(1, len(errors), str(errors))
        self.assertIn("'llm_config.provider_tools[1]' must be a dict, got str.", errors[0])

    def test_near_miss_key_at_network_level_reported_once(self) -> None:
        """
        A near-miss key on the network llm_config yields one error, even though both agents inherit it.
        """
        validator: DictionaryValidator = self.create_validator()
        config: Dict[str, Any] = self.restore("hello_world.hocon")
        self._network_llm_config(config)["builtin_tools"] = [self.WEB_SEARCH]

        errors: List[str] = validator.validate(config)
        self.assertEqual(1, len(errors), str(errors))
        self.assertIn("network 'llm_config.builtin_tools' is not a recognized key; did you mean 'provider_tools'?",
                      errors[0])

    def test_near_miss_key_on_one_agent(self) -> None:
        """
        A near-miss key on a single agent is reported under that agent's name only.
        """
        validator: DictionaryValidator = self.create_validator()
        config: Dict[str, Any] = self.restore("hello_world.hocon")
        announcer_llm_config: Dict[str, Any] = self._agent(config, "announcer").get("llm_config")
        announcer_llm_config["server_tools"] = [self.WEB_SEARCH]

        errors: List[str] = validator.validate(config)
        self.assertEqual(1, len(errors), str(errors))
        self.assertIn("announcer 'llm_config.server_tools' is not a recognized key", errors[0])

    def test_provider_tools_inside_fallbacks_entry(self) -> None:
        """
        A provider_tools key inside a fallbacks entry is reported with that entry's index.
        """
        validator: DictionaryValidator = self.create_validator()
        config: Dict[str, Any] = self.restore("hello_world.hocon")
        self._network_llm_config(config)["fallbacks"] = [
            {"model_name": "gpt-5.2"},
            {"model_name": "gpt-4.1", "provider_tools": [self.WEB_SEARCH]},
        ]

        errors: List[str] = validator.validate(config)
        self.assertEqual(1, len(errors), str(errors))
        self.assertIn("network 'llm_config.fallbacks[1].provider_tools' is ignored at runtime", errors[0])

    def test_provider_tools_inside_nested_peer_group(self) -> None:
        """
        A provider_tools key inside a peer group is reported with a dotted index path.
        """
        validator: DictionaryValidator = self.create_validator()
        config: Dict[str, Any] = self.restore("hello_world.hocon")
        self._network_llm_config(config)["fallbacks"] = [
            [
                {"model_name": "gpt-5.2"},
                {"model_name": "gpt-4.1", "provider_tools": [self.WEB_SEARCH]},
            ],
            {"model_name": "gpt-5.2"},
        ]

        errors: List[str] = validator.validate(config)
        self.assertEqual(1, len(errors), str(errors))
        self.assertIn("'llm_config.fallbacks[0.1].provider_tools' is ignored at runtime", errors[0])

    def test_gemini_model_name_with_other_tools(self) -> None:
        """
        With a Gemini model on the network, the agent that has tools is flagged and the leaf is not.
        """
        validator: DictionaryValidator = self.create_validator()
        config: Dict[str, Any] = self.restore("hello_world.hocon")
        self._with_network_llm_config(config, {"model_name": self.GEMINI_MODEL,
                                               "provider_tools": [self.GOOGLE_SEARCH]})

        errors: List[str] = validator.validate(config)
        self.assertEqual(1, len(errors), str(errors))
        self.assertIn("announcer declares Gemini provider_tools together with other tools (synonymizer)", errors[0])

    def test_gemini_explicit_class_with_other_tools(self) -> None:
        """
        An explicit "class": "gemini" is treated the same as a Gemini model_name.
        """
        validator: DictionaryValidator = self.create_validator()
        config: Dict[str, Any] = self.restore("hello_world.hocon")
        self._with_network_llm_config(config, {"class": "gemini", "model_name": self.GEMINI_MODEL,
                                               "provider_tools": [self.GOOGLE_SEARCH]})

        errors: List[str] = validator.validate(config)
        self.assertEqual(1, len(errors), str(errors))
        self.assertIn("announcer declares Gemini provider_tools together with other tools", errors[0])

    def test_gemini_capitalized_class_with_other_tools(self) -> None:
        """
        A "class" spelled "Gemini" builds a Gemini model at runtime, so it is subject to the rules too.
        """
        validator: DictionaryValidator = self.create_validator()
        config: Dict[str, Any] = self.restore("hello_world.hocon")
        self._with_network_llm_config(config, {"class": "Gemini", "model_name": self.GEMINI_MODEL,
                                               "provider_tools": [self.GOOGLE_SEARCH]})

        errors: List[str] = validator.validate(config)
        self.assertEqual(1, len(errors), str(errors))
        self.assertIn("announcer declares Gemini provider_tools together with other tools", errors[0])

    def test_gemini_two_entries_on_tool_less_agent(self) -> None:
        """
        Two Gemini built-ins on an agent with no other tools yield only the one-entry error.
        """
        validator: DictionaryValidator = self.create_validator()
        config: Dict[str, Any] = self.restore("hello_world.hocon")
        self._with_network_llm_config(config, {"model_name": self.GEMINI_MODEL})
        self._agent(config, "synonymizer")["llm_config"] = {
            "provider_tools": [self.GOOGLE_SEARCH, self.CODE_EXECUTION],
        }

        errors: List[str] = validator.validate(config)
        self.assertEqual(1, len(errors), str(errors))
        self.assertIn("synonymizer declares 2 Gemini provider_tools; Gemini supports one built-in entry per agent",
                      errors[0])

    def test_inherited_two_gemini_entries_reported_once(self) -> None:
        """
        Two inherited Gemini built-ins are reported once under the network label, not once per agent.
        """
        validator: DictionaryValidator = self.create_validator()
        config: Dict[str, Any] = self.restore("hello_world.hocon")
        self._with_network_llm_config(config, {"model_name": self.GEMINI_MODEL,
                                               "provider_tools": [self.GOOGLE_SEARCH, self.CODE_EXECUTION]})

        errors: List[str] = validator.validate(config)
        # The announcer also has tools, so its mixing error is expected alongside the one count error.
        self.assertEqual(2, len(errors), str(errors))
        self.assertIn("network declares 2 Gemini provider_tools; Gemini supports one built-in entry per agent",
                      errors[0])
        self.assertIn("announcer declares Gemini provider_tools together with other tools", errors[1])

    def test_agent_clears_inherited_gemini_list(self) -> None:
        """
        An agent-level empty list clears the inherited Gemini list, so the agent with tools is not flagged.
        """
        validator: DictionaryValidator = self.create_validator()
        config: Dict[str, Any] = self.restore("hello_world.hocon")
        self._with_network_llm_config(config, {"model_name": self.GEMINI_MODEL,
                                               "provider_tools": [self.GOOGLE_SEARCH]})
        self._agent(config, "announcer")["llm_config"] = {"provider_tools": []}

        errors: List[str] = validator.validate(config)
        self.assertEqual(0, len(errors), str(errors))

    def test_non_llm_tools_are_not_subject_to_gemini_rules(self) -> None:
        """
        A coded tool (with args.tools) and a toolbox tool that inherit a Gemini list are not flagged.
        """
        validator: DictionaryValidator = self.create_validator()
        config: Dict[str, Any] = self.restore("hello_world.hocon")
        self._add_non_llm_tools(config)
        self._with_network_llm_config(config, {"model_name": self.GEMINI_MODEL,
                                               "provider_tools": [self.GOOGLE_SEARCH]})
        # The announcer clears the list so that only the non-LLM tools and the tool-less leaf inherit it.
        self._agent(config, "announcer")["llm_config"] = {"provider_tools": []}

        errors: List[str] = validator.validate(config)
        self.assertEqual(0, len(errors), str(errors))

    def test_gemini_in_second_fallback(self) -> None:
        """
        A Gemini model anywhere in the fallbacks chain makes the top-level provider_tools subject to the rules.
        """
        validator: DictionaryValidator = self.create_validator()
        config: Dict[str, Any] = self.restore("hello_world.hocon")
        self._with_network_llm_config(config, {
            "provider_tools": [self.GOOGLE_SEARCH],
            "fallbacks": [
                {"model_name": "gpt-4.1"},
                {"model_name": self.GEMINI_MODEL},
            ],
        })

        errors: List[str] = validator.validate(config)
        self.assertEqual(1, len(errors), str(errors))
        self.assertIn("announcer declares Gemini provider_tools together with other tools", errors[0])

    def test_dotted_user_class_is_not_gemini(self) -> None:
        """
        A dotted user class with provider_tools and tools is not subject to the Gemini rules.
        """
        validator: DictionaryValidator = self.create_validator()
        config: Dict[str, Any] = self.restore("hello_world.hocon")
        self._with_network_llm_config(config, {
            "class": "langchain_openai.chat_models.base.ChatOpenAI",
            "model_name": "gpt-4.1",
            "provider_tools": [self.WEB_SEARCH],
        })

        errors: List[str] = validator.validate(config)
        self.assertEqual(0, len(errors), str(errors))

    def test_unknown_model_name_is_not_gemini(self) -> None:
        """
        A model_name llm_info does not know resolves to no class, so no Gemini error is produced.
        """
        validator: DictionaryValidator = self.create_validator()
        config: Dict[str, Any] = self.restore("hello_world.hocon")
        self._with_network_llm_config(config, {"model_name": "model-neuro-san-has-never-heard-of",
                                               "provider_tools": [self.GOOGLE_SEARCH]})

        errors: List[str] = validator.validate(config)
        self.assertEqual(0, len(errors), str(errors))

    def test_name_to_spec_candidate_runs_shape_checks(self) -> None:
        """
        A name -> spec dictionary (no "tools" key at the top) still gets the shape checks.
        """
        validator: DictionaryValidator = self.create_validator()
        name_to_spec: Dict[str, Any] = {
            "announcer": {
                "name": "announcer",
                "llm_config": {"model_name": "gpt-4.1", "provider_tools": "web_search"},
                "tools": ["synonymizer"],
            },
            "synonymizer": {
                "name": "synonymizer",
                "llm_config": {"model_name": "gpt-4.1"},
            },
        }

        errors: List[str] = validator.validate(name_to_spec)
        self.assertEqual(1, len(errors), str(errors))
        self.assertIn("announcer 'llm_config.provider_tools' must be a list, got str.", errors[0])

    def test_top_level_tools_not_a_list_is_skipped(self) -> None:
        """
        A top-level "tools" that is not a list is left alone instead of crashing inside
        the filter chain.
        """
        validator: DictionaryValidator = self.create_validator()
        config: Dict[str, Any] = {
            "llm_config": {"model_name": "gpt-4.1", "provider_tools": [{"type": "web_search"}]},
            "tools": "announcer",
        }

        self.assertEqual([], validator.validate(config))

    def test_scalar_tool_entry_is_skipped(self) -> None:
        """
        A scalar entry in the top-level "tools" list is left alone instead of crashing
        inside the filter chain.
        """
        validator: DictionaryValidator = self.create_validator()
        config: Dict[str, Any] = {
            "llm_config": {"model_name": "gpt-4.1"},
            "tools": [{"name": "announcer", "llm_config": {"model_name": "gpt-4.1"}}, 5],
        }

        self.assertEqual([], validator.validate(config))

    def test_missing_llm_info_file_still_runs_shape_checks(self) -> None:
        """
        An llm_info_file that does not exist costs only the class checks; shape checks still run and nothing raises.
        """
        validator: DictionaryValidator = self.create_validator()
        config: Dict[str, Any] = self.restore("hello_world.hocon")
        self._gemini_network_with_llm_info_file(config, "/no/such/directory/llm_info.hocon")

        self._assert_only_synonymizer_shape_error(validator, config)

    def test_directory_llm_info_file_still_runs_shape_checks(self) -> None:
        """
        An llm_info_file that is a directory costs only the class checks; shape checks still run and nothing raises.
        """
        validator: DictionaryValidator = self.create_validator()
        config: Dict[str, Any] = self.restore("hello_world.hocon")
        directory: str = tempfile.mkdtemp()
        self.addCleanup(os.rmdir, directory)
        self._gemini_network_with_llm_info_file(config, directory)

        self._assert_only_synonymizer_shape_error(validator, config)

    def test_string_llm_info_entry_does_not_raise(self) -> None:
        """
        A user llm_info entry that is not a dictionary resolves to no class, so nothing raises and nothing is flagged.
        """
        validator: DictionaryValidator = self.create_validator()
        config: Dict[str, Any] = self.restore("hello_world.hocon")
        config["llm_info_file"] = self._write_llm_info_file(f'{{ "{self.GEMINI_MODEL}": "just a string" }}')
        self._with_network_llm_config(config, {"model_name": self.GEMINI_MODEL,
                                               "provider_tools": [self.GOOGLE_SEARCH]})

        errors: List[str] = validator.validate(config)
        self.assertEqual(0, len(errors), str(errors))

    def test_llm_info_not_loaded_without_provider_tools_list(self) -> None:
        """
        Neither an unchanged network nor a shape error alone makes the validator parse llm_info.
        """
        validator: DictionaryValidator = self.create_validator()
        config: Dict[str, Any] = self.restore("hello_world.hocon")

        with patch.object(ProviderToolsNetworkValidator, "load_factory", return_value=None) as load_factory:
            validator.validate(config)
            self._network_llm_config(config)["provider_tools"] = "web_search"
            validator.validate(config)

        load_factory.assert_not_called()

    def test_llm_info_loaded_once_for_provider_tools_list(self) -> None:
        """
        A non-empty list on an LLM agent loads llm_info exactly once for the whole network.
        """
        validator: DictionaryValidator = self.create_validator()
        config: Dict[str, Any] = self.restore("hello_world.hocon")
        self._with_network_llm_config(config, {"model_name": "gpt-4.1", "provider_tools": [self.WEB_SEARCH]})

        with patch.object(ProviderToolsNetworkValidator, "load_factory", return_value=None) as load_factory:
            validator.validate(config)

        load_factory.assert_called_once()
