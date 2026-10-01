
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
from typing import List
from typing import Optional
from typing import Tuple

from logging import Logger
from logging import getLogger

from neuro_san.internals.run_context.langchain.llms.default_llm_factory import DefaultLlmFactory
from neuro_san.internals.validation.network.abstract_network_validator import AbstractNetworkValidator


class ProviderToolsFitChecker:
    """
    Checks that an agent's `llm_config.provider_tools` list fits every model the agent
    would build. These are the provider_tools rules that need llm_info, so the
    ProviderToolsNetworkValidator runs them only once it has a loaded DefaultLlmFactory.

    For each agent, every model in its fallback chain is resolved to an llm_info class,
    that class's root family (through `extends`) and whether the class declares support
    for provider_tools. Then, in this order:

      - Support: a model whose class does not declare `provider_tools` in its own llm_info
        args cannot use the list at all, so it is reported and skipped by the shape rules.
      - One provider: the runtime binds the same list to every fallback and rejects a
        chain whose models use different provider classes, so mixed classes are reported.
      - Shape: each dictionary must look like what the family expects. Gemini built-ins
        are keyed by tool name, OpenAI and Anthropic entries carry a string `type`, and an
        Anthropic `type` must be a server tool, since neuro-san does not execute the
        client-side ones.
      - Gemini: a Gemini agent may not mix its built-in with other `tools` and gets one
        built-in entry.

    A model that resolves to no llm_info class (a dotted user class, a non-string class, or
    a model llm_info does not know) is left alone by every rule. Messages about an agent that runs the
    network's own model with the network's own list are labelled "network", and exact
    duplicate messages are dropped, so an inherited mistake is reported once.
    """

    # The llm_config key this checker is about.
    KEY: str = "provider_tools"

    # The llm_config key holding alternative model configs, possibly nested one level as peer groups.
    FALLBACKS_KEY: str = "fallbacks"

    # The label used in messages about a problem that belongs to the network-level llm_config.
    NETWORK_LABEL: str = "network"

    # The root llm_info classes whose provider_tools shapes are known.
    OPENAI_FAMILY: str = "openai"
    ANTHROPIC_FAMILY: str = "anthropic"
    GEMINI_FAMILY: str = "gemini"

    # Prefixes of the dated Anthropic tool types that run on Anthropic's servers, e.g. web_search_20250305.
    ANTHROPIC_SERVER_PREFIXES: List[str] = ["web_search_", "web_fetch_", "code_execution_", "tool_search_"]

    # Undated Anthropic server tool types, which must match exactly.
    ANTHROPIC_SERVER_TYPES: List[str] = ["mcp_toolset"]

    # Prefixes of Anthropic tool types that expect the client to execute them.
    ANTHROPIC_CLIENT_PREFIXES: List[str] = ["bash_", "text_editor_", "computer_", "memory_"]

    # The llm_config keys that decide which models are built and which list is bound to them.
    # An agent whose values all equal the network's is running the network's own setup.
    MODEL_KEYS: List[str] = ["provider_tools", "model_name", "class", "fallbacks"]

    # The model label used in messages when a model config has no model_name.
    DEFAULT_MODEL_LABEL: str = "default"

    def __init__(self, factory: DefaultLlmFactory, network_name: Optional[str]) -> None:
        """
        Constructor

        :param factory: The loaded DefaultLlmFactory holding the llm_info the network runs with
        :param network_name: The agent network name for diagnostic log lines
        """
        self.logger: Logger = getLogger(self.__class__.__name__)
        self.factory: DefaultLlmFactory = factory
        self.network_name: Optional[str] = network_name

    def check(self,
              candidates: List[Tuple[str, Dict[str, Any], Dict[str, Any]]],
              inherited: Optional[Dict[str, Any]]) -> List[str]:
        """
        Runs every rule over the agents that bind a non-empty provider_tools list.

        :param candidates: (agent name, agent spec, merged llm_config) triples for the agents
                whose provider_tools is a non-empty list
        :param inherited: The network-level llm_config the agents inherited from, or None
        :return: A list of error messages without exact duplicates, in first-occurrence order
        """
        self.logger.debug("Checking %s provider_tools against the models they bind to...", self.network_name)

        errors: List[str] = []
        inherited_count: int = 0

        for agent_name, agent, llm_config in candidates:
            models: List[Tuple[str, str, str, bool]] = self.resolve_models(llm_config)
            label: str = self.message_label(agent_name, llm_config, inherited)
            provider_tools: List[Any] = llm_config.get(self.KEY)

            errors.extend(self.check_support(label, models))
            errors.extend(self.check_single_provider(label, models))
            errors.extend(self.check_shapes(label, provider_tools, models))

            if not self.resolves_to_gemini(models):
                continue

            # The mixing rule depends on the agent's own tools, so it is always the agent's problem.
            errors.extend(self.validate_gemini_mixing(agent_name, agent))

            if len(provider_tools) > 1:
                if self.is_inherited(llm_config, inherited, self.KEY):
                    # Every agent that kept the network-level list would repeat this one,
                    # so it is reported once under NETWORK_LABEL below.
                    inherited_count = len(provider_tools)
                else:
                    errors.append(self.gemini_count_message(agent_name, len(provider_tools)))

        if inherited_count > 0:
            errors.insert(0, self.gemini_count_message(self.NETWORK_LABEL, inherited_count))

        return self.dedupe(errors)

    def resolve_models(self, llm_config: Dict[str, Any]) -> List[Tuple[str, str, str, bool]]:
        """
        Resolves every model an llm_config would build to what the rules need to know about it.

        :param llm_config: The agent's merged llm_config
        :return: One (model label, class name, family, declares) tuple per model whose class
                is in the llm_info "classes" table: the model_name (or DEFAULT_MODEL_LABEL),
                the lowercased class name, the root class it descends from, and whether the
                class declares provider_tools support. A model with a non-string "class", or
                one that resolves to no llm_info class, is left out, so no rule ever judges it.
        """
        resolved: List[Tuple[str, str, str, bool]] = []
        for model_config in self.collect_model_configs(llm_config):
            class_value: Any = model_config.get("class")
            if class_value and not isinstance(class_value, str):
                # The runtime rejects such a class before it reads provider_tools, so nothing
                # is known about the provider. None and "" fall through to model_name there
                # and in get_chat_class_name(), so they are not skipped here.
                continue
            class_name: Optional[str] = self.factory.get_chat_class_name(model_config)
            if not isinstance(class_name, str):
                # An unknown model: nothing is known about its provider.
                continue
            # The runtime lowercases "class" before its policy lookup, so "Gemini" is gemini.
            class_name = class_name.lower()
            family: Optional[str] = self.factory.get_chat_class_family(class_name)
            if family is None:
                # A dotted user class is not in the classes table, so there is nothing to check it against.
                continue
            declares: bool = self.factory.declares_provider_tools(class_name)
            resolved.append((self._model_label(model_config), class_name, family, declares))
        return resolved

    @staticmethod
    def _model_label(model_config: Dict[str, Any]) -> str:
        """
        Names one model config for a message.

        :param model_config: The llm_config dictionary that becomes one model
        :return: Its model_name as a string, or DEFAULT_MODEL_LABEL when it has none
        """
        model_name: Any = model_config.get("model_name")
        if model_name is None:
            return ProviderToolsFitChecker.DEFAULT_MODEL_LABEL
        return str(model_name)

    def check_support(self, label: str, models: List[Tuple[str, str, str, bool]]) -> List[str]:
        """
        Reports every model whose class does not support provider_tools.

        :param label: The agent name, or NETWORK_LABEL for an inherited setup
        :param models: The resolved models from resolve_models()
        :return: A list of error messages
        """
        errors: List[str] = []
        for model_label, class_name, _, declares in models:
            if not declares:
                errors.append(f"{label} declares provider_tools for model '{model_label}' whose class '{class_name}'"
                              f" does not support them; in the stock llm_info only the openai, azure-openai,"
                              f" anthropic and gemini classes do.")
        return errors

    def check_single_provider(self, label: str, models: List[Tuple[str, str, str, bool]]) -> List[str]:
        """
        Reports a fallback chain whose models use more than one llm_info class.

        Classes are compared rather than families because that is what the runtime does:
        azure-openai and openai have different LlmPolicy types, so the runtime rejects a
        chain that mixes them once provider_tools is non-empty.

        :param label: The agent name, or NETWORK_LABEL for an inherited setup
        :param models: The resolved models from resolve_models()
        :return: A list with one error message, or an empty list
        """
        class_names: List[str] = []
        for _, class_name, _, _ in models:
            if class_name not in class_names:
                class_names.append(class_name)
        if len(class_names) <= 1:
            return []

        class_names.sort()
        return [f"{label} 'llm_config.provider_tools' requires every fallback model to use the same provider;"
                f" found classes {', '.join(class_names)}."]

    def check_shapes(self,
                     label: str,
                     provider_tools: List[Any],
                     models: List[Tuple[str, str, str, bool]]) -> List[str]:
        """
        Checks every provider_tools dictionary against the family of each supporting model.

        :param label: The agent name, or NETWORK_LABEL for an inherited setup
        :param provider_tools: The agent's provider_tools list
        :param models: The resolved models from resolve_models()
        :return: A list of error messages, possibly repeating one per same-family model
                until check() drops the duplicates
        """
        errors: List[str] = []
        for _, _, family, declares in models:
            if not declares:
                # Already reported by check_support(); its shapes are beside the point.
                continue
            for index, entry in enumerate(provider_tools):
                if isinstance(entry, dict):
                    # Anything else was already reported by the validator's shape check.
                    errors.extend(self.check_entry_shape(label, index, entry, family))
        return errors

    def check_entry_shape(self, label: str, index: int, entry: Dict[str, Any], family: str) -> List[str]:
        """
        Checks one provider_tools dictionary against one family's expected shape.

        :param label: The agent name, or NETWORK_LABEL for an inherited setup
        :param index: The position of the entry in the provider_tools list
        :param entry: The provider_tools dictionary
        :param family: The root llm_info class of the model the entry is bound to
        :return: A list of error messages; empty for a family whose shapes are not known here
        """
        if family == self.GEMINI_FAMILY:
            return self.check_gemini_entry(label, index, entry)
        if family == self.OPENAI_FAMILY:
            return self.check_openai_entry(label, index, entry)
        if family == self.ANTHROPIC_FAMILY:
            return self.check_anthropic_entry(label, index, entry)
        return []

    @staticmethod
    def check_gemini_entry(label: str, index: int, entry: Dict[str, Any]) -> List[str]:
        """
        Reports a Gemini entry written in the OpenAI/Anthropic shape.

        :param label: The agent name, or NETWORK_LABEL for an inherited setup
        :param index: The position of the entry in the provider_tools list
        :param entry: The provider_tools dictionary
        :return: A list of error messages
        """
        if "type" not in entry:
            return []
        return [f"{label} 'llm_config.provider_tools[{index}]' has a 'type' key, which is the OpenAI/Anthropic shape;"
                ' Gemini built-ins are keyed by tool name, such as {"google_search": {}}.']

    @staticmethod
    def check_openai_entry(label: str, index: int, entry: Dict[str, Any]) -> List[str]:
        """
        Reports an OpenAI entry without a string type.

        There is no list of accepted OpenAI types: they change often, and a prefix rule
        would collide with names such as web_search_preview.

        :param label: The agent name, or NETWORK_LABEL for an inherited setup
        :param index: The position of the entry in the provider_tools list
        :param entry: The provider_tools dictionary
        :return: A list of error messages
        """
        if isinstance(entry.get("type"), str):
            return []
        return [f"{label} 'llm_config.provider_tools[{index}]' has no string 'type';"
                ' OpenAI built-ins look like {"type": "web_search"}.']

    def check_anthropic_entry(self, label: str, index: int, entry: Dict[str, Any]) -> List[str]:
        """
        Reports an Anthropic entry without a string type, or whose type is not a server tool.

        :param label: The agent name, or NETWORK_LABEL for an inherited setup
        :param index: The position of the entry in the provider_tools list
        :param entry: The provider_tools dictionary
        :return: A list of error messages
        """
        tool_type: Any = entry.get("type")
        if not isinstance(tool_type, str):
            return [f"{label} 'llm_config.provider_tools[{index}]' has no string 'type';"
                    ' Anthropic server tools look like {"type": "web_search_20250305", "name": "web_search"}.']

        families: List[str] = self.ANTHROPIC_SERVER_PREFIXES + self.ANTHROPIC_SERVER_TYPES
        server_families: str = ", ".join(families)
        if self._starts_with_any(tool_type, self.ANTHROPIC_CLIENT_PREFIXES):
            return [f"{label} 'llm_config.provider_tools[{index}]' type '{tool_type}' is an Anthropic client-side"
                    f" tool, which neuro-san does not execute; only server tools ({server_families}) are supported."]

        if not self._is_anthropic_server_tool(tool_type):
            # The last family is joined with "and" so the message reads as a sentence.
            listed: str = ", ".join(families[:-1])
            return [f"{label} 'llm_config.provider_tools[{index}]' type '{tool_type}' is not an Anthropic server"
                    f" tool; supported families are {listed} and {families[-1]}."]
        return []

    def _is_anthropic_server_tool(self, tool_type: str) -> bool:
        """
        Tells whether an Anthropic tool type names a server tool.

        Dated families match by prefix, so a new date suffix still passes. Undated types such
        as mcp_toolset must match exactly, so a misspelling is caught here instead of by Anthropic.

        :param tool_type: The "type" string of a provider_tools entry
        :return: True when the type is a server tool neuro-san can bind
        """
        if tool_type in self.ANTHROPIC_SERVER_TYPES:
            return True
        return self._starts_with_any(tool_type, self.ANTHROPIC_SERVER_PREFIXES)

    @staticmethod
    def _starts_with_any(value: str, prefixes: List[str]) -> bool:
        """
        Tells whether a string starts with any of the given prefixes.

        :param value: The string to test
        :param prefixes: The prefixes to try
        :return: True when value starts with at least one prefix
        """
        for prefix in prefixes:
            if value.startswith(prefix):
                return True
        return False

    def message_label(self, agent_name: str, llm_config: Dict[str, Any], inherited: Optional[Dict[str, Any]]) -> str:
        """
        Picks the label for messages about an agent's models and list.

        :param agent_name: The name of the agent
        :param llm_config: The agent's merged llm_config
        :param inherited: The network-level llm_config, or None when there is none
        :return: NETWORK_LABEL when every MODEL_KEYS value equals the network's, because the
                agent then runs the network's own model with the network's own list and the
                problem is the network's; otherwise the agent name
        """
        if inherited is None:
            return agent_name
        for key in self.MODEL_KEYS:
            if llm_config.get(key) != inherited.get(key):
                return agent_name
        return self.NETWORK_LABEL

    @staticmethod
    def is_inherited(llm_config: Dict[str, Any], inherited: Optional[Dict[str, Any]], key: str) -> bool:
        """
        Tells whether an llm_config key holds the value copied in from the network-level llm_config.

        :param llm_config: The agent's merged llm_config
        :param inherited: The network-level llm_config, or None when there is none
        :param key: The llm_config key to compare
        :return: True when the network-level llm_config has the key and the agent's value equals it
        """
        if inherited is None or key not in inherited:
            return False
        return llm_config.get(key) == inherited.get(key)

    @staticmethod
    def dedupe(messages: List[str]) -> List[str]:
        """
        Drops exact duplicate messages, keeping the first occurrence of each in place.

        :param messages: The messages collected over every agent
        :return: The messages without repeats, in their original order
        """
        unique: List[str] = []
        for message in messages:
            if message not in unique:
                unique.append(message)
        return unique

    def validate_gemini_mixing(self, agent_name: str, agent: Dict[str, Any]) -> List[str]:
        """
        Reports a Gemini agent that would bind function tools alongside its built-in.

        Gemini 2.x answers 400 "Multiple tools are supported only when they are all search
        tools" when a built-in is mixed with function tools, and the presence of a built-in
        dict makes langchain-google-genai drop nullable/anyOf from the sibling tool schemas.
        Only the agent's `tools` count: that is the list CallingActivation hands to the
        model. `args.tools` is the coded-tool convention and never reaches an LLM.

        :param agent_name: The name of the agent being validated
        :param agent: The agent spec dictionary
        :return: A list of error messages
        """
        other_tools: List[Any] = AbstractNetworkValidator.coerce_tools(agent)
        if len(other_tools) == 0:
            return []

        tool_names: List[str] = []
        for tool in other_tools:
            tool_names.append(self.tool_label(tool))
        return [f"{agent_name} declares Gemini provider_tools together with other tools"
                f" ({', '.join(tool_names)}); Gemini rejects built-in tools mixed with function tools"
                f" and mis-converts the other tools' schemas,"
                f" so move the built-in to an agent with no other tools."]

    @staticmethod
    def tool_label(tool: Any) -> str:
        """
        Names one entry of an agent's `tools` list for a message.

        :param tool: The tools entry: an agent name or URL string, or an MCP server dictionary
        :return: The string itself, an MCP server's "url", or the type name as a last resort
        """
        if isinstance(tool, str):
            return tool
        if isinstance(tool, dict):
            url: Any = tool.get("url")
            if isinstance(url, str):
                return url
        return type(tool).__name__

    @staticmethod
    def gemini_count_message(label: str, count: int) -> str:
        """
        Builds the message for more than one Gemini built-in entry.

        :param label: The agent name, or NETWORK_LABEL for an inherited network-level list
        :param count: The number of provider_tools entries
        :return: The error message
        """
        return (f"{label} declares {count} Gemini provider_tools;"
                f" Gemini supports one built-in entry per agent in this release.")

    def resolves_to_gemini(self, models: List[Tuple[str, str, str, bool]]) -> bool:
        """
        Tells whether any model the agent would build is a Gemini model that takes provider_tools.

        :param models: The resolved models from resolve_models()
        :return: True when at least one model is of the gemini family and its class
                declares provider_tools support
        """
        for _, _, family, declares in models:
            if family == self.GEMINI_FAMILY and declares:
                return True
        return False

    def collect_model_configs(self, llm_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Lists the configs that actually become models, the way create_llm_with_fallbacks() sees them.

        When a non-empty fallbacks list is present the runtime builds only its entries
        (peer groups flattened) and never the enclosing llm_config, whose model_name is
        then just an inherited leftover; otherwise the llm_config is the one model.

        :param llm_config: The agent's merged llm_config
        :return: The list of llm_config dictionaries that would each become a model
        """
        fallbacks: Any = llm_config.get(self.FALLBACKS_KEY)
        if isinstance(fallbacks, list) and len(fallbacks) > 0:
            model_configs: List[Dict[str, Any]] = []
            self.flatten_fallbacks(fallbacks, model_configs)
            return model_configs
        return [llm_config]

    def flatten_fallbacks(self, fallbacks: List[Any], into: List[Dict[str, Any]]) -> None:
        """
        Appends every dict entry of a fallbacks list to `into`, descending into peer groups.

        :param fallbacks: The fallbacks list, whose entries are dicts or lists of dicts
        :param into: The list that receives the dict entries, in order
        """
        for entry in fallbacks:
            if isinstance(entry, list):
                self.flatten_fallbacks(entry, into)
            elif isinstance(entry, dict):
                into.append(entry)
