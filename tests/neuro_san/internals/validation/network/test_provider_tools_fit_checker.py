
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
from typing import Optional
from typing import Tuple

from unittest import TestCase
from unittest.mock import patch

from typing_extensions import override

from neuro_san.internals.run_context.langchain.llms.default_llm_factory import DefaultLlmFactory
from neuro_san.internals.validation.network.provider_tools_fit_checker import ProviderToolsFitChecker


# The rule matrix (support, one provider, three shape families, labelling) legitimately needs more than 20 cases.
# pylint: disable=too-many-public-methods
class TestProviderToolsFitChecker(TestCase):
    """
    Unit tests for ProviderToolsFitChecker class.

    Every test hands the checker (agent name, agent spec, merged llm_config) candidates
    directly, the way ProviderToolsNetworkValidator does once it has loaded llm_info, and
    asserts the exact list of messages that comes back.
    """

    # The agent under test and a second agent it can call.
    AGENT: str = "front"
    OTHER_AGENT: str = "leaf"

    # Models the stock llm_info knows, one per class of interest.
    OPENAI_MODEL: str = "gpt-4.1"
    SECOND_OPENAI_MODEL: str = "gpt-5.2"
    ANTHROPIC_ALIAS: str = "claude-fable"
    GEMINI_MODEL: str = "gemini-2.5-flash"
    AZURE_MODEL: str = "azure-gpt-4o"
    OLLAMA_MODEL: str = "llama3.1"
    ANTHROPIC_BEDROCK_ALIAS: str = "bedrock-claude-opus"
    BEDROCK_ALIAS: str = "bedrock-us-claude-sonnet-4"

    # Things that resolve to no llm_info class.
    UNKNOWN_MODEL: str = "model-neuro-san-has-never-heard-of"
    DOTTED_CLASS: str = "langchain_openai.chat_models.base.ChatOpenAI"

    # A user class (extending openai unless a test says otherwise) and a model using it, defined by
    # _user_class_hocon().
    USER_CLASS: str = "my-class"
    USER_MODEL: str = "my-model"

    # Provider tool dictionaries in each provider's shape.
    WEB_SEARCH: Dict[str, Any] = {"type": "web_search"}
    GOOGLE_SEARCH: Dict[str, Any] = {"google_search": {}}
    CODE_EXECUTION: Dict[str, Any] = {"code_execution": {}}
    ANTHROPIC_WEB_SEARCH: Dict[str, Any] = {"type": "web_search_20250305", "name": "web_search"}
    ANTHROPIC_MCP_TOOLSET: Dict[str, Any] = {"type": "mcp_toolset", "mcp_server_name": "docs"}
    ANTHROPIC_BASH: Dict[str, Any] = {"type": "bash_20250124", "name": "bash"}

    # Message tails shared by several tests; the label goes in front.
    OPENAI_NO_TYPE: str = (" 'llm_config.provider_tools[0]' has no string 'type';"
                           ' OpenAI built-ins look like {"type": "web_search"}.')
    ANTHROPIC_NOT_SERVER_TOOL: str = (" 'llm_config.provider_tools[0]' type 'web_search' is not an Anthropic server"
                                      " tool; supported families are web_search_, web_fetch_, code_execution_,"
                                      " tool_search_ and mcp_toolset.")
    UNSUPPORTED_TAIL: str = (" does not support them; in the stock llm_info only the openai, azure-openai,"
                             " anthropic and gemini classes do.")
    GEMINI_MIXED_WITH_LEAF: str = (
        "front declares Gemini provider_tools together with other tools (leaf); Gemini rejects built-in tools"
        " mixed with function tools and mis-converts the other tools' schemas, so move the built-in to an agent"
        " with no other tools.")

    @override
    def setUp(self) -> None:
        """
        Pins the environment and loads the stock default_llm_info.hocon.

        AGENT_LLM_INFO_FILE is removed so that a deployer override present in the environment
        cannot change the class table these tests check; patch.dict restores it afterwards.
        OPENAI_API_KEY is pinned to a dummy so nothing here can see a real provider key.
        """
        env_patcher: Any = patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"})
        env_patcher.start()
        self.addCleanup(env_patcher.stop)
        os.environ.pop("AGENT_LLM_INFO_FILE", None)

        # Loaded after the environment is pinned so the stock hocon is what gets read.
        self.factory: DefaultLlmFactory = DefaultLlmFactory()
        self.factory.load()

    def _load_factory_with_extra_llm_info(self, extra_hocon: str) -> DefaultLlmFactory:
        """
        Builds a second factory whose llm_info is the stock file overlaid with the given hocon text.

        :param extra_hocon: The contents of a user llm_info_file to overlay on the defaults
        :return: A loaded DefaultLlmFactory using that overlay
        """
        # delete=False because the restorer opens the file by path after this handle is closed.
        # The cleanup removes it even if the test fails.
        with tempfile.NamedTemporaryFile(mode="w", suffix=".hocon", delete=False) as hocon_file:
            hocon_file.write(extra_hocon)
            hocon_path: str = hocon_file.name
        self.addCleanup(os.remove, hocon_path)

        factory: DefaultLlmFactory = DefaultLlmFactory({"llm_info_file": hocon_path})
        factory.load()
        return factory

    def _user_class_hocon(self, with_marker: bool, extends: Optional[str] = "openai") -> str:
        """
        Builds llm_info hocon text defining USER_CLASS and USER_MODEL using it.

        :param with_marker: True to declare "provider_tools" in the class's own args
        :param extends: The stock class USER_CLASS extends, or None for a root class of its own
        :return: The hocon text
        """
        marker: str = ""
        if with_marker:
            marker = '"provider_tools": null,'
        extends_line: str = ""
        if extends is not None:
            extends_line = f'"extends": "{extends}",'
        return f"""
        {{
            "classes": {{
                "{self.USER_CLASS}": {{
                    {extends_line}
                    "args": {{
                        {marker}
                        "temperature": 0.5
                    }}
                }}
            }},
            "{self.USER_MODEL}": {{
                "class": "{self.USER_CLASS}",
                "max_output_tokens": 1000
            }}
        }}
        """

    @staticmethod
    def _candidate(name: str,
                   llm_config: Dict[str, Any],
                   tools: Optional[List[Any]] = None) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
        """
        Builds one candidate triple the way ProviderToolsNetworkValidator hands them over.

        :param name: The agent name
        :param llm_config: The agent's merged llm_config
        :param tools: The agent's tools list, or None for an agent with no tools
        :return: The (agent name, agent spec, merged llm_config) triple
        """
        agent: Dict[str, Any] = {"name": name, "instructions": "x", "llm_config": llm_config}
        if tools is not None:
            agent["tools"] = tools
        return name, agent, llm_config

    def _checker(self, factory: Optional[DefaultLlmFactory] = None) -> ProviderToolsFitChecker:
        """
        Builds the checker under test.

        :param factory: The factory to check against, or None for the stock one
        :return: A ProviderToolsFitChecker
        """
        use_factory: Optional[DefaultLlmFactory] = factory
        if use_factory is None:
            use_factory = self.factory
        return ProviderToolsFitChecker(use_factory, "test_network")

    def _check(self,
               llm_config: Dict[str, Any],
               tools: Optional[List[Any]] = None,
               factory: Optional[DefaultLlmFactory] = None) -> List[str]:
        """
        Checks a single agent named AGENT with no network-level llm_config.

        :param llm_config: The agent's merged llm_config
        :param tools: The agent's tools list, or None for an agent with no tools
        :param factory: The factory to check against, or None for the stock one
        :return: The checker's messages
        """
        return self._checker(factory).check([self._candidate(self.AGENT, llm_config, tools)], None)

    def _unsupported(self, label: str, model_label: str, class_name: str) -> str:
        """
        Builds the expected message for a class that does not support provider_tools.

        :param label: The agent name or "network"
        :param model_label: The model_name in the message
        :param class_name: The class name in the message
        :return: The full expected message
        """
        return (f"{label} declares provider_tools for model '{model_label}' whose class '{class_name}'"
                f"{self.UNSUPPORTED_TAIL}")

    # ---- Part 1: the class must support provider_tools -----------------------------------------------

    def test_ollama_class_is_unsupported(self) -> None:
        """
        An ollama model cannot take provider_tools, and nothing else is said about the list.
        """
        errors: List[str] = self._check({"model_name": self.OLLAMA_MODEL, "provider_tools": [self.WEB_SEARCH]})

        self.assertEqual([self._unsupported(self.AGENT, self.OLLAMA_MODEL, "ollama")], errors)

    def test_azure_openai_accepts_openai_shape(self) -> None:
        """
        azure-openai declares the marker in its own args and extends openai, so an OpenAI dictionary fits.
        """
        errors: List[str] = self._check({"model_name": self.AZURE_MODEL, "provider_tools": [self.WEB_SEARCH]})

        self.assertEqual([], errors)

    def test_azure_openai_applies_openai_shape_rule(self) -> None:
        """
        A Gemini-shaped dictionary on azure-openai is judged by the OpenAI family rule it inherits.
        """
        errors: List[str] = self._check({"model_name": self.AZURE_MODEL, "provider_tools": [self.GOOGLE_SEARCH]})

        self.assertEqual([self.AGENT + " 'llm_config.provider_tools[0]' has no string 'type';"
                          ' OpenAI built-ins look like {"type": "web_search"}.'], errors)

    def test_anthropic_bedrock_class_is_unsupported(self) -> None:
        """
        anthropic-bedrock only inherits the marker through "extends", so it is unsupported.
        """
        errors: List[str] = self._check({"model_name": self.ANTHROPIC_BEDROCK_ALIAS,
                                         "provider_tools": [self.ANTHROPIC_WEB_SEARCH]})

        self.assertEqual([self._unsupported(self.AGENT, self.ANTHROPIC_BEDROCK_ALIAS, "anthropic-bedrock")], errors)

    def test_bedrock_class_is_unsupported(self) -> None:
        """
        The bedrock class never had the marker, so it is unsupported.
        """
        errors: List[str] = self._check({"model_name": self.BEDROCK_ALIAS,
                                         "provider_tools": [self.ANTHROPIC_WEB_SEARCH]})

        self.assertEqual([self._unsupported(self.AGENT, self.BEDROCK_ALIAS, "bedrock")], errors)

    def test_missing_model_name_is_labelled_default(self) -> None:
        """
        A model config with a class but no model_name is named "default" in the message.
        """
        errors: List[str] = self._check({"class": "ollama", "provider_tools": [self.WEB_SEARCH]})

        self.assertEqual([self._unsupported(self.AGENT, "default", "ollama")], errors)

    def test_class_is_lowercased_in_messages(self) -> None:
        """
        A capitalized class is looked up and reported lowercased, the way the runtime treats it.
        """
        errors: List[str] = self._check({"class": "Ollama", "model_name": self.OLLAMA_MODEL,
                                         "provider_tools": [self.WEB_SEARCH]})

        self.assertEqual([self._unsupported(self.AGENT, self.OLLAMA_MODEL, "ollama")], errors)

    # ---- Part 2: one provider per fallback chain -------------------------------------------------------

    def test_openai_and_anthropic_fallbacks_are_mixed_providers(self) -> None:
        """
        A chain of an OpenAI and an Anthropic model is reported once, with the classes sorted.

        The Anthropic dictionary has a string type, so both families accept its shape and the
        mixing is the only problem.
        """
        errors: List[str] = self._check({
            "provider_tools": [self.ANTHROPIC_WEB_SEARCH],
            "fallbacks": [{"model_name": self.OPENAI_MODEL}, {"model_name": self.ANTHROPIC_ALIAS}],
        })

        self.assertEqual(["front 'llm_config.provider_tools' requires every fallback model to use the same provider;"
                          " found classes anthropic, openai."], errors)

    def test_openai_and_azure_fallbacks_are_mixed_classes(self) -> None:
        """
        openai and azure-openai are one family but two classes, which is what the runtime compares.
        """
        errors: List[str] = self._check({
            "provider_tools": [self.WEB_SEARCH],
            "fallbacks": [{"model_name": self.OPENAI_MODEL}, {"model_name": self.AZURE_MODEL}],
        })

        self.assertEqual([
            "front 'llm_config.provider_tools' requires every fallback model to use the same provider;"
            " found classes azure-openai, openai.",
        ], errors)

    def test_peer_group_fallbacks_are_flattened(self) -> None:
        """
        A model inside a peer group counts towards the chain like any other fallback.
        """
        errors: List[str] = self._check({
            "provider_tools": [self.ANTHROPIC_WEB_SEARCH],
            "fallbacks": [
                [{"model_name": self.OPENAI_MODEL}, {"model_name": self.ANTHROPIC_ALIAS}],
                {"model_name": self.SECOND_OPENAI_MODEL},
            ],
        })

        self.assertEqual(["front 'llm_config.provider_tools' requires every fallback model to use the same provider;"
                          " found classes anthropic, openai."], errors)

    # ---- Part 3: dictionaries must match the provider -------------------------------------------------

    def test_openai_dict_on_anthropic_model(self) -> None:
        """
        An OpenAI built-in has a string type, but not one of Anthropic's server tool families.
        """
        errors: List[str] = self._check({"model_name": self.ANTHROPIC_ALIAS, "provider_tools": [self.WEB_SEARCH]})

        self.assertEqual([self.AGENT + self.ANTHROPIC_NOT_SERVER_TOOL], errors)

    def test_anthropic_client_side_tool_is_reported(self) -> None:
        """
        A client-side Anthropic tool is a real Anthropic type, but neuro-san does not execute it.
        """
        errors: List[str] = self._check({"model_name": self.ANTHROPIC_ALIAS,
                                         "provider_tools": [self.ANTHROPIC_BASH]})

        self.assertEqual(["front 'llm_config.provider_tools[0]' type 'bash_20250124' is an Anthropic client-side"
                          " tool, which neuro-san does not execute; only server tools (web_search_, web_fetch_,"
                          " code_execution_, tool_search_, mcp_toolset) are supported."], errors)

    def test_anthropic_server_tools_are_accepted(self) -> None:
        """
        A dated server tool and the undated mcp_toolset both pass.
        """
        errors: List[str] = self._check({"model_name": self.ANTHROPIC_ALIAS,
                                         "provider_tools": [self.ANTHROPIC_WEB_SEARCH, self.ANTHROPIC_MCP_TOOLSET]})

        self.assertEqual([], errors)

    def test_anthropic_dict_without_type(self) -> None:
        """
        An Anthropic entry with no type at all gets the Anthropic example, not the OpenAI one.
        """
        errors: List[str] = self._check({"model_name": self.ANTHROPIC_ALIAS,
                                         "provider_tools": [{"name": "web_search"}]})

        self.assertEqual(["front 'llm_config.provider_tools[0]' has no string 'type'; Anthropic server tools look"
                          ' like {"type": "web_search_20250305", "name": "web_search"}.'], errors)

    def test_gemini_dict_on_openai_model(self) -> None:
        """
        A Gemini built-in has no type key, which OpenAI needs.
        """
        errors: List[str] = self._check({"model_name": self.OPENAI_MODEL, "provider_tools": [self.GOOGLE_SEARCH]})

        self.assertEqual([self.AGENT + self.OPENAI_NO_TYPE], errors)

    def test_openai_dict_on_gemini_model(self) -> None:
        """
        An OpenAI built-in has a type key, which a Gemini built-in never has.
        """
        errors: List[str] = self._check({"model_name": self.GEMINI_MODEL, "provider_tools": [self.WEB_SEARCH]})

        self.assertEqual(["front 'llm_config.provider_tools[0]' has a 'type' key, which is the OpenAI/Anthropic"
                          ' shape; Gemini built-ins are keyed by tool name, such as {"google_search": {}}.'], errors)

    def test_valid_gemini_entry_on_tool_less_agent(self) -> None:
        """
        One Gemini built-in on a Gemini agent with no other tools is fine.
        """
        errors: List[str] = self._check({"model_name": self.GEMINI_MODEL, "provider_tools": [self.GOOGLE_SEARCH]})

        self.assertEqual([], errors)

    def test_second_bad_entry_is_reported_by_index(self) -> None:
        """
        Only the entry that does not fit is reported, with its own index.
        """
        errors: List[str] = self._check({"model_name": self.OPENAI_MODEL,
                                         "provider_tools": [self.WEB_SEARCH, self.GOOGLE_SEARCH]})

        self.assertEqual(["front 'llm_config.provider_tools[1]' has no string 'type';"
                          ' OpenAI built-ins look like {"type": "web_search"}.'], errors)

    # ---- Models that resolve to no llm_info class are left alone ----------------------------------------

    def test_dotted_class_is_skipped(self) -> None:
        """
        A dotted user class is not in the classes table, so nothing about its list is judged.
        """
        errors: List[str] = self._check({"class": self.DOTTED_CLASS, "model_name": self.OPENAI_MODEL,
                                         "provider_tools": [self.GOOGLE_SEARCH]})

        self.assertEqual([], errors)

    def test_unknown_model_is_skipped(self) -> None:
        """
        A model llm_info does not know resolves to no class, so nothing about its list is judged.
        """
        errors: List[str] = self._check({"model_name": self.UNKNOWN_MODEL, "provider_tools": [self.GOOGLE_SEARCH]})

        self.assertEqual([], errors)

    def test_non_string_class_is_skipped(self) -> None:
        """
        The runtime rejects a class that is not a string before it reads provider_tools, so the
        model_name next to it is not judged in its place.
        """
        errors: List[str] = self._check({"class": 123, "model_name": self.OPENAI_MODEL,
                                         "provider_tools": [self.GOOGLE_SEARCH]})

        self.assertEqual([], errors)

    # ---- User classes opt in through their own args ----------------------------------------------------

    def test_user_class_with_marker_accepts_openai_shape(self) -> None:
        """
        A user class extending openai that declares the marker is supported and takes OpenAI shapes.
        """
        factory: DefaultLlmFactory = self._load_factory_with_extra_llm_info(self._user_class_hocon(True))

        errors: List[str] = self._check({"model_name": self.USER_MODEL, "provider_tools": [self.WEB_SEARCH]},
                                        factory=factory)

        self.assertEqual([], errors)

    def test_user_class_with_marker_applies_openai_shape_rule(self) -> None:
        """
        The same user class inherits the OpenAI family, so a Gemini-shaped entry is reported.
        """
        factory: DefaultLlmFactory = self._load_factory_with_extra_llm_info(self._user_class_hocon(True))

        errors: List[str] = self._check({"model_name": self.USER_MODEL, "provider_tools": [self.GOOGLE_SEARCH]},
                                        factory=factory)

        self.assertEqual([self.AGENT + self.OPENAI_NO_TYPE], errors)

    def test_user_class_without_marker_is_unsupported(self) -> None:
        """
        Without the marker in its own args, extending openai is not enough to be supported.
        """
        factory: DefaultLlmFactory = self._load_factory_with_extra_llm_info(self._user_class_hocon(False))

        errors: List[str] = self._check({"model_name": self.USER_MODEL, "provider_tools": [self.WEB_SEARCH]},
                                        factory=factory)

        self.assertEqual([self._unsupported(self.AGENT, self.USER_MODEL, self.USER_CLASS)], errors)

    def test_root_user_class_with_marker_has_no_shape_rule(self) -> None:
        """
        A user class with no "extends" that declares the marker is supported, but it is a family
        of its own whose shapes are not known here, so neither dictionary shape is judged.
        """
        factory: DefaultLlmFactory = self._load_factory_with_extra_llm_info(
            self._user_class_hocon(True, extends=None))

        for entry in [self.GOOGLE_SEARCH, self.WEB_SEARCH]:
            errors: List[str] = self._check({"model_name": self.USER_MODEL, "provider_tools": [entry]},
                                            factory=factory)

            self.assertEqual([], errors, str(entry))

    def test_user_class_extending_gemini_gets_gemini_rules(self) -> None:
        """
        A user class extending gemini with the marker is a Gemini model, so mixing its built-in
        with other tools is reported.
        """
        factory: DefaultLlmFactory = self._load_factory_with_extra_llm_info(
            self._user_class_hocon(True, extends=ProviderToolsFitChecker.GEMINI_FAMILY))

        errors: List[str] = self._check({"model_name": self.USER_MODEL, "provider_tools": [self.GOOGLE_SEARCH]},
                                        tools=[self.OTHER_AGENT], factory=factory)

        self.assertEqual([self.GEMINI_MIXED_WITH_LEAF], errors)

    # ---- Labelling and dedup -----------------------------------------------------------------------------

    def test_inherited_setup_is_reported_once_as_network(self) -> None:
        """
        Two agents running the network's own model with the network's own list yield one "network" message.
        """
        inherited: Dict[str, Any] = {"model_name": self.OPENAI_MODEL, "provider_tools": [self.GOOGLE_SEARCH]}
        candidates: List[Tuple[str, Dict[str, Any], Dict[str, Any]]] = [
            self._candidate(self.AGENT, deepcopy(inherited)),
            self._candidate(self.OTHER_AGENT, deepcopy(inherited)),
        ]

        errors: List[str] = self._checker().check(candidates, inherited)

        self.assertEqual([ProviderToolsFitChecker.NETWORK_LABEL + self.OPENAI_NO_TYPE], errors)

    def test_agent_overriding_model_is_labelled_by_name(self) -> None:
        """
        An agent that moves the inherited OpenAI list onto a Claude model owns the resulting problem.
        """
        inherited: Dict[str, Any] = {"model_name": self.OPENAI_MODEL, "provider_tools": [self.WEB_SEARCH]}
        candidates: List[Tuple[str, Dict[str, Any], Dict[str, Any]]] = [
            self._candidate(self.AGENT, {"model_name": self.ANTHROPIC_ALIAS, "provider_tools": [self.WEB_SEARCH]}),
            self._candidate(self.OTHER_AGENT, deepcopy(inherited)),
        ]

        errors: List[str] = self._checker().check(candidates, inherited)

        self.assertEqual([self.AGENT + self.ANTHROPIC_NOT_SERVER_TOOL], errors)

    def test_same_family_fallbacks_report_shape_once(self) -> None:
        """
        Two OpenAI fallbacks bound to one bad dictionary produce the shape message once, not twice.
        """
        errors: List[str] = self._check({
            "provider_tools": [self.GOOGLE_SEARCH],
            "fallbacks": [{"model_name": self.OPENAI_MODEL}, {"model_name": self.SECOND_OPENAI_MODEL}],
        })

        self.assertEqual([self.AGENT + self.OPENAI_NO_TYPE], errors)

    # ---- The Gemini rules run through the checker -----------------------------------------------------

    def test_gemini_mixing_and_count_rules(self) -> None:
        """
        A Gemini agent with other tools and two built-ins gets both Gemini messages, mixing first.
        """
        errors: List[str] = self._check({"model_name": self.GEMINI_MODEL,
                                         "provider_tools": [self.GOOGLE_SEARCH, self.CODE_EXECUTION]},
                                        tools=[self.OTHER_AGENT])

        self.assertEqual([
            self.GEMINI_MIXED_WITH_LEAF,
            "front declares 2 Gemini provider_tools; Gemini supports one built-in entry per agent in this release.",
        ], errors)

    def test_inherited_gemini_count_is_reported_first_as_network(self) -> None:
        """
        An inherited two-entry Gemini list is reported once under "network", ahead of the agents' own messages.
        """
        inherited: Dict[str, Any] = {"model_name": self.GEMINI_MODEL,
                                     "provider_tools": [self.GOOGLE_SEARCH, self.CODE_EXECUTION]}
        candidates: List[Tuple[str, Dict[str, Any], Dict[str, Any]]] = [
            self._candidate(self.AGENT, deepcopy(inherited), tools=[self.OTHER_AGENT]),
            self._candidate(self.OTHER_AGENT, deepcopy(inherited)),
        ]

        errors: List[str] = self._checker().check(candidates, inherited)

        self.assertEqual([
            "network declares 2 Gemini provider_tools; Gemini supports one built-in entry per agent in this release.",
            self.GEMINI_MIXED_WITH_LEAF,
        ], errors)

    def test_no_candidates_yield_no_messages(self) -> None:
        """
        With nothing to check, the checker says nothing.
        """
        self.assertEqual([], self._checker().check([], None))
