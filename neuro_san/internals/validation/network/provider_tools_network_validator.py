
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
from typing import ClassVar
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

from logging import Logger
from logging import getLogger
from threading import Lock

from typing_extensions import override

from neuro_san.internals.graph.filters.network_config_filter_chain import NetworkConfigFilterChain
from neuro_san.internals.run_context.langchain.llms.default_llm_factory import DefaultLlmFactory
from neuro_san.internals.validation.network.abstract_network_validator import AbstractNetworkValidator


class ProviderToolsNetworkValidator(AbstractNetworkValidator):
    """
    AbstractNetworkValidator that checks the `llm_config.provider_tools` key so that
    mistakes surface at registry load (and in the hocon validator CLI) instead of as
    provider 400s at request time, or not at all:

      - Shape: `provider_tools` must be absent, null, or a list of dicts.
      - Near-miss keys: spellings such as `builtin_tools` or `server_tools` are not
        recognized anywhere at runtime (unknown llm_config keys vanish silently), so
        they are reported with a hint towards `provider_tools`.
      - Misplaced key: the runtime reads `provider_tools` only from the top level of an
        llm_config (see DefaultLlmFactory.create_llm_with_fallbacks), so a copy inside a
        `fallbacks` entry is ignored and is reported as such.
      - Gemini rules: Gemini rejects a built-in tool mixed with function tools and
        supports one built-in entry per agent, so an LLM agent whose llm_config (or any
        of its fallbacks) resolves to the "gemini" class is checked for both. Coded tools
        and toolbox tools never build a model, so they are left out of these two rules.

    Network-level `llm_config` values are copied into every agent by DefaultsConfigFilter,
    so the shape, near-miss and misplaced-key checks run once on the network-level
    llm_config (labelled "network") and are skipped for an agent whose value is the
    inherited one, to avoid reporting the same mistake once per agent. The Gemini mixing
    rule depends on each agent's own tools, so it always runs per agent on the merged
    config; the one-entry rule for an inherited list is likewise reported once.

    The Gemini rules are the only ones that need llm_info, and parsing it costs a good
    fraction of a second under HoconParseLock, so it is loaded only when some LLM agent
    carries a non-empty provider_tools list, and the stock llm_info is parsed once per
    process. When llm_info cannot be loaded (bad `llm_info_file`, for instance) a warning
    is logged and only the class-independent checks run. This validator never raises.
    """

    # The llm_config key this validator is about.
    KEY: str = "provider_tools"

    # Spellings seen for provider_tools that the runtime silently ignores.
    NEAR_MISS_KEYS: List[str] = [
        "provider_tool",
        "builtin_tool",
        "builtin_tools",
        "built_in_tools",
        "server_tool",
        "server_tools",
    ]

    # The llm_info class whose provider_tools carry extra restrictions.
    GEMINI_CLASS: str = "gemini"

    # The llm_config key holding alternative model configs, possibly nested one level as peer groups.
    FALLBACKS_KEY: str = "fallbacks"

    # The label used in messages about the network-level llm_config.
    NETWORK_LABEL: str = "network"

    # The stock llm_info, loaded on first use and shared by every instance in the process.
    # The bundled default_llm_info.hocon cannot change while the process runs, so sharing
    # it is safe; a factory reading a user llm_info_file is never cached (see load_factory).
    _stock_factory: ClassVar[Optional[DefaultLlmFactory]] = None

    # Guards _stock_factory: manifest networks are validated from a thread pool.
    _stock_factory_lock: ClassVar[Lock] = Lock()

    def __init__(self, network_name: Optional[str] = None) -> None:
        """
        Constructor

        :param network_name: The agent network name for diagnostic log lines
        """
        self.logger: Logger = getLogger(self.__class__.__name__)
        self.network_name: Optional[str] = network_name

    @override
    def validate(self, candidate: Dict[str, Any]) -> List[str]:
        """
        Validate the agent network.

        A full network (one with a "tools" key) is run through the standard filter chain
        first so that every agent carries its merged llm_config. The manifest path hands
        us an already-filtered config and the reservation path a raw one; for a config
        whose llm_configs are already dictionaries the chain changes nothing the second
        time around, so both end up in the same place. A name -> spec dictionary has no
        network-level llm_config and no llm_info_file, so it is checked as-is against the
        stock llm_info.

        :param candidate: The agent network or name -> spec dictionary to validate
        :return: A list of error messages
        """
        if not candidate:
            return super().validate(candidate)

        use_candidate: Dict[str, Any] = candidate
        network_llm_config: Optional[Dict[str, Any]] = None
        factory_config: Optional[Dict[str, Any]] = None
        if "tools" in candidate:
            # The filter chain expects a list of agent dictionaries and raises on anything
            # else. A malformed top-level "tools" is not this validator's concern, so skip
            # it rather than crash inside the chain.
            tools: Any = candidate.get("tools")
            if not isinstance(tools, list):
                return []
            for tool in tools:
                if not isinstance(tool, dict):
                    return []
            use_candidate = NetworkConfigFilterChain().filter_config(candidate)
            # The top-level llm_config survives filtering, and comparing agents against the
            # filtered copy (rather than the raw one) means commondefs substitutions do not
            # make an inherited value look like an agent-level override.
            network_llm_config = use_candidate.get("llm_config")
            factory_config = use_candidate

        name_to_spec: Dict[str, Any] = self.get_name_to_spec(use_candidate)
        errors: List[str] = self.validate_network(name_to_spec, network_llm_config, factory_config)
        self.report(errors)
        return errors

    @override
    def validate_name_to_spec_dict(self, name_to_spec: Dict[str, Any]) -> List[str]:
        """
        Validate the agent network, specifically in the form of a name -> agent spec dictionary.

        In this form there is no network-level llm_config to deduplicate against and no
        llm_info_file to honor, so every agent is checked against the stock llm_info.

        :param name_to_spec: The name -> agent spec dictionary to validate
        :return: A list of error messages
        """
        errors: List[str] = self.validate_network(name_to_spec, None, None)
        self.report(errors)
        return errors

    def validate_network(self,
                         name_to_spec: Dict[str, Any],
                         network_llm_config: Optional[Dict[str, Any]],
                         factory_config: Optional[Dict[str, Any]]) -> List[str]:
        """
        Runs every check over the network-level llm_config and then over each agent.

        :param name_to_spec: The name -> agent spec dictionary to validate
        :param network_llm_config: The network-level llm_config that agents inherit from,
                or None when there is none
        :param factory_config: The filtered network config handed to DefaultLlmFactory
                when llm_info turns out to be needed, or None to use the stock llm_info
        :return: A list of error messages
        """
        errors: List[str] = []

        self.logger.debug("Validating %s provider_tools...", self.network_name)

        inherited: Optional[Dict[str, Any]] = None
        if isinstance(network_llm_config, dict):
            inherited = network_llm_config
            errors.extend(self.validate_llm_config(self.NETWORK_LABEL, network_llm_config, None))

        # The class-independent checks need no llm_info. While running them, note the
        # agents that would actually bind a non-empty provider_tools list to a model:
        # only those can trip the Gemini rules, so llm_info is loaded only for them.
        gemini_candidates: List[Tuple[str, Dict[str, Any], Dict[str, Any]]] = []
        for agent_name, agent in name_to_spec.items():
            if not isinstance(agent, dict):
                continue
            llm_config: Any = agent.get("llm_config")
            if not isinstance(llm_config, dict):
                # Nothing of ours to check. A non-dict llm_config is not this validator's business.
                continue
            errors.extend(self.validate_llm_config(agent_name, llm_config, inherited))
            if self.binds_provider_tools(agent, llm_config):
                gemini_candidates.append((agent_name, agent, llm_config))

        if len(gemini_candidates) == 0:
            return errors

        factory: Optional[DefaultLlmFactory] = self.load_factory(factory_config)
        if factory is None:
            return errors

        errors.extend(self.validate_gemini_agents(gemini_candidates, inherited, factory))
        return errors

    def load_factory(self, config: Optional[Dict[str, Any]]) -> Optional[DefaultLlmFactory]:
        """
        Loads the llm_info the network would use at runtime, for class resolution.

        A network without an llm_info_file of its own (and no AGENT_LLM_INFO_FILE in the
        environment) reads only the stock default_llm_info.hocon, which is parsed once per
        process and shared. A user llm_info_file is read afresh every time: the manifest
        watcher re-validates a network when its files change and the runtime reloads its
        own factory then (AsyncAgentService.reload_factories), so a cached copy could
        reject a network whose llm_info the user has just fixed.

        :param config: The filtered network config, whose "llm_info_file" key is honored
                the same way the runtime honors it, or None to use the stock llm_info
                (plus any AGENT_LLM_INFO_FILE override from the environment)
        :return: A loaded DefaultLlmFactory, or None when llm_info could not be loaded
        """
        try:
            factory: DefaultLlmFactory = DefaultLlmFactory(config)
            if factory.get_llm_info_file() is not None:
                factory.load()
                return factory
            return self.load_stock_factory(factory)
        except (ValueError, TypeError, OSError) as exception:
            # A bad llm_info_file is the runtime's problem to report when an agent is
            # created. Here it only costs the class-dependent checks; the shape checks
            # still run, so do not let it take down the whole validation. OSError covers
            # a missing file as well as a directory or an unreadable file in its place.
            self.logger.warning("%s: could not load llm_info, skipping provider_tools class checks: %s",
                                self.network_name, exception)
            return None

    @classmethod
    def load_stock_factory(cls, factory: DefaultLlmFactory) -> DefaultLlmFactory:
        """
        Returns the process-wide stock factory, loading the given one to become it if there is none yet.

        :param factory: An unloaded DefaultLlmFactory that reads only the stock llm_info
        :return: The shared, loaded DefaultLlmFactory for the stock llm_info
        :raises ValueError: if the stock llm_info cannot be parsed
        """
        # The load happens under the lock so that concurrent first callers do not each
        # parse the file; the parse itself is serialized by HoconParseLock anyway.
        with cls._stock_factory_lock:
            if cls._stock_factory is None:
                factory.load()
                cls._stock_factory = factory
            return cls._stock_factory

    def validate_llm_config(self,
                            label: str,
                            llm_config: Dict[str, Any],
                            inherited: Optional[Dict[str, Any]]) -> List[str]:
        """
        Runs the class-independent checks (shape, near-miss keys, misplaced key) on one llm_config.

        :param label: The agent name, or NETWORK_LABEL for the network-level llm_config
        :param llm_config: The llm_config dictionary to check
        :param inherited: The network-level llm_config this one inherited from, or None.
                A key whose value equals the inherited one was already reported under
                NETWORK_LABEL and is skipped here.
        :return: A list of error messages
        """
        errors: List[str] = []

        if not self.is_inherited(llm_config, inherited, self.KEY):
            errors.extend(self.validate_shape(label, llm_config.get(self.KEY)))

        for key in self.NEAR_MISS_KEYS:
            if key in llm_config and not self.is_inherited(llm_config, inherited, key):
                errors.append(self.near_miss_message(label, key))

        if not self.is_inherited(llm_config, inherited, self.FALLBACKS_KEY):
            errors.extend(self.validate_fallbacks(label, llm_config.get(self.FALLBACKS_KEY), ""))

        return errors

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
    def validate_shape(label: str, provider_tools: Any) -> List[str]:
        """
        Validate that provider_tools is absent, null, or a list of dicts.

        :param label: The agent name, or NETWORK_LABEL for the network-level llm_config
        :param provider_tools: The value of the provider_tools key
        :return: A list of error messages
        """
        if provider_tools is None:
            return []
        if not isinstance(provider_tools, list):
            return [f"{label} 'llm_config.provider_tools' must be a list, got {type(provider_tools).__name__}."]

        errors: List[str] = []
        for index, entry in enumerate(provider_tools):
            # Each entry is passed through to the provider unchanged, and every provider takes a dict.
            if not isinstance(entry, dict):
                errors.append(f"{label} 'llm_config.provider_tools[{index}]' must be a dict,"
                              f" got {type(entry).__name__}.")
        return errors

    @staticmethod
    def near_miss_message(label: str, key_path: str) -> str:
        """
        Builds the message for a key that looks like a misspelling of provider_tools.

        :param label: The agent name, or NETWORK_LABEL for the network-level llm_config
        :param key_path: The key path below llm_config, such as "builtin_tools" or "fallbacks[1].builtin_tools"
        :return: The error message
        """
        return f"{label} 'llm_config.{key_path}' is not a recognized key; did you mean 'provider_tools'?"

    def validate_fallbacks(self, label: str, fallbacks: Any, index_prefix: str) -> List[str]:
        """
        Reports a provider_tools key or a near-miss key inside any fallbacks entry.

        The runtime only reads provider_tools from the top level of the llm_config and
        binds that one list to every fallback, so a copy inside an entry is dead
        configuration. Peer groups (a list inside the fallbacks list) are recursed into,
        with their position recorded as a dotted index path such as "0.2".

        :param label: The agent name, or NETWORK_LABEL for the network-level llm_config
        :param fallbacks: The value of the fallbacks key; anything but a list is left alone
        :param index_prefix: The dotted index path of the enclosing peer group including its
                trailing ".", or "" at the top level
        :return: A list of error messages
        """
        errors: List[str] = []
        if not isinstance(fallbacks, list):
            return errors

        for index, entry in enumerate(fallbacks):
            index_path: str = f"{index_prefix}{index}"
            if isinstance(entry, list):
                errors.extend(self.validate_fallbacks(label, entry, f"{index_path}."))
                continue
            if not isinstance(entry, dict):
                continue

            if self.KEY in entry:
                errors.append(f"{label} 'llm_config.fallbacks[{index_path}].provider_tools' is ignored at runtime;"
                              f" declare provider_tools at the top level of llm_config"
                              f" so it applies to every fallback.")

            for key in self.NEAR_MISS_KEYS:
                if key in entry:
                    errors.append(self.near_miss_message(label, f"fallbacks[{index_path}].{key}"))

        return errors

    def binds_provider_tools(self, agent: Dict[str, Any], llm_config: Dict[str, Any]) -> bool:
        """
        Tells whether an agent would hand a non-empty provider_tools list to a model.

        :param agent: The agent spec dictionary
        :param llm_config: The agent's merged llm_config
        :return: True when the agent builds an LLM and its provider_tools is a non-empty list
        """
        provider_tools: Any = llm_config.get(self.KEY)
        if not isinstance(provider_tools, list) or len(provider_tools) == 0:
            return False
        return self.is_llm_agent(agent)

    @staticmethod
    def is_llm_agent(agent: Dict[str, Any]) -> bool:
        """
        Tells whether an agent spec builds a model at all.

        This mirrors the order of ActivationFactory.BASE_PREPPERS: a "toolbox" key selects
        a ToolboxActivation and a "class" key a ClassActivation (coded tool), and neither
        reads llm_config even though DefaultsConfigFilter copies one in. Everything else
        becomes a Branch or FrontMan activation, whose CallingActivation builds the model.

        :param agent: The agent spec dictionary
        :return: True when the spec is neither a toolbox tool nor a coded tool
        """
        return agent.get("toolbox") is None and agent.get("class") is None

    def validate_gemini_agents(self,
                               candidates: List[Tuple[str, Dict[str, Any], Dict[str, Any]]],
                               inherited: Optional[Dict[str, Any]],
                               factory: DefaultLlmFactory) -> List[str]:
        """
        Applies the Gemini-specific provider_tools rules to the agents that bind a list.

        Gemini 2.x answers 400 "Multiple tools are supported only when they are all search
        tools" when a built-in is mixed with function tools, and the presence of a built-in
        dict makes langchain-google-genai drop nullable/anyOf from the sibling tool schemas,
        so both conditions are reported before any request is made.

        :param candidates: (agent name, agent spec, merged llm_config) triples for the agents
                whose provider_tools is a non-empty list, as binds_provider_tools() sees it
        :param inherited: The network-level llm_config, or None when there is none
        :param factory: The loaded DefaultLlmFactory used to resolve classes
        :return: A list of error messages
        """
        errors: List[str] = []
        inherited_count: int = 0

        for agent_name, agent, llm_config in candidates:
            if not self.resolves_to_gemini(llm_config, factory):
                continue

            errors.extend(self.validate_gemini_mixing(agent_name, agent))

            provider_tools: List[Any] = llm_config.get(self.KEY)
            if len(provider_tools) > 1:
                if self.is_inherited(llm_config, inherited, self.KEY):
                    # Every agent that kept the network-level list would repeat this one,
                    # so it is reported once under NETWORK_LABEL below.
                    inherited_count = len(provider_tools)
                else:
                    errors.append(self.gemini_count_message(agent_name, len(provider_tools)))

        if inherited_count > 0:
            errors.insert(0, self.gemini_count_message(self.NETWORK_LABEL, inherited_count))

        return errors

    def validate_gemini_mixing(self, agent_name: str, agent: Dict[str, Any]) -> List[str]:
        """
        Reports a Gemini agent that would bind function tools alongside its built-in.

        Only the agent's `tools` count: that is the list CallingActivation hands to the
        model. `args.tools` is the coded-tool convention and never reaches an LLM.

        :param agent_name: The name of the agent being validated
        :param agent: The agent spec dictionary
        :return: A list of error messages
        """
        other_tools: List[Any] = self.coerce_tools(agent)
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

    def resolves_to_gemini(self, llm_config: Dict[str, Any], factory: DefaultLlmFactory) -> bool:
        """
        Tells whether any model the llm_config would build resolves to the Gemini class.

        :param llm_config: The agent's merged llm_config
        :param factory: The loaded DefaultLlmFactory used to resolve classes
        :return: True when the llm_config itself, or any fallbacks entry, resolves to GEMINI_CLASS
        """
        for model_config in self.collect_model_configs(llm_config):
            class_name: Optional[str] = factory.get_chat_class_name(model_config)
            # Compared case-insensitively because the runtime lowercases "class" before its
            # policy lookup (StandardLangChainLlmFactory.create_llm_resources), so a
            # "Gemini" spelling builds a Gemini model just the same.
            if isinstance(class_name, str) and class_name.lower() == self.GEMINI_CLASS:
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

    def report(self, errors: List[str]) -> None:
        """
        Logs the errors found, if any.

        :param errors: The list of error messages
        """
        if len(errors) > 0:
            # Only warn if there is a problem
            self.logger.warning("%s: %s", self.network_name, errors)
