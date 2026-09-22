
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
from typing import Sequence
from typing import Tuple
from typing import Union

from os import cpu_count
from os import environ
from os import pathsep
import json
from logging import getLogger
from logging import Logger

from concurrent.futures import ProcessPoolExecutor
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from json.decoder import JSONDecodeError
from multiprocessing import get_context
from time import perf_counter

from pyparsing.exceptions import ParseException
from pyparsing.exceptions import ParseSyntaxException

from leaf_common.config.config_filter import ConfigFilter
from leaf_common.config.dictionary_overlay import DictionaryOverlay
from leaf_common.config.file_of_class import FileOfClass
from leaf_common.logging.sensitive_logger import SensitiveLogger
from leaf_common.persistence.interface.restorer import Restorer

from neuro_san import REGISTRIES_DIR
from neuro_san.internals.graph.persistence.agent_filetree_mapper import AgentFileTreeMapper
from neuro_san.internals.graph.persistence.agent_network_restorer import AgentNetworkRestorer
from neuro_san.internals.graph.persistence.manifest_filter_chain import ManifestFilterChain
from neuro_san.internals.graph.persistence.raw_manifest_restorer import RawManifestRestorer
from neuro_san.internals.graph.persistence.served_manifest_config_filter import ServedManifestConfigFilter
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.interfaces.agent_name_mapper import AgentNameMapper
from neuro_san.internals.interfaces.storage_class import StorageClass
from neuro_san.internals.utils.mcp_tool_name_policy import McpToolNamePolicy
from neuro_san.internals.validation.network.manifest_network_validator import ManifestNetworkValidator


class RegistryManifestRestorer(Restorer):
    """
    Implementation of the Restorer interface that reads the manifest file
    for agent networks/registries.
    """

    def __init__(self, manifest_files: Union[str, List[str]] = None, agent_mapper: AgentNameMapper = None):
        """
        Constructor

        :param manifest_files: Either:
            * A single local name for the manifest file listing the agents to host.
            * A list of local names for multiple manifest files to host
            * None (the default) which gets a single manifest file from a known source.
        :param agent_mapper: optional AgentNameMapper;
            if None, AgentFileTreeMapper instance will be used.
        """
        self.agent_mapper: AgentNameMapper = agent_mapper
        if not self.agent_mapper:
            self.agent_mapper = AgentFileTreeMapper()

        self.manifest_files: List[str] = []
        self.periodic_configs: Dict[str, Dict[str, Any]] = {}

        if manifest_files is None:
            # We have no manifest list coming in, so check an env variable for a definition.
            manifest_file: str = environ.get("AGENT_MANIFEST_FILE")
            if manifest_file is None:
                # No env var, so fallback to what is coded in this repo.
                manifest_file = REGISTRIES_DIR.get_file_in_basis("manifest.hocon")

            # Add what was found above
            use_files: List[str] = manifest_file.split(pathsep)
            self.manifest_files.extend(use_files)
        elif isinstance(manifest_files, str):
            use_files: List[str] = manifest_files.split(pathsep)
            self.manifest_files.extend(use_files)
        else:
            self.manifest_files = manifest_files

        self.logger: Logger = getLogger(self.__class__.__name__)

    def restore_from_files(self, file_references: Sequence[str]) -> Dict[str, Dict[str, AgentNetwork]]:
        """
        :param file_references: The sequence of file references to use when restoring.
        :return: a nested map of storage type -> (mapping of name -> agent networks)
        """
        all_agent_networks: Dict[str, Dict[str, AgentNetwork]] = {}
        overlayer = DictionaryOverlay()

        # Loop through all the manifest files in the list to make a composite
        for manifest_file in file_references:
            agents_from_one_manifest: Dict[str, Dict[str, AgentNetwork]] = self.restore_one_manifest(manifest_file)
            # Do a deep update() with the overlayer.
            all_agent_networks = overlayer.overlay(all_agent_networks, agents_from_one_manifest)

        # Loop through the agent networks dictionary removing any references to None values
        # for networks. This indicates they should not be served.
        config_filter: ConfigFilter = ServedManifestConfigFilter(manifest_file=None,
                                                                 warn_on_skip=False,
                                                                 entry_for_skipped=False)
        for storage_type, storage_dict in all_agent_networks.items():
            all_agent_networks[storage_type] = config_filter.filter_config(storage_dict)

        # Two networks can only be seen to claim the same MCP tool name once every
        # manifest has been overlaid and the unserved (None) entries are gone,
        # so this has to run last.
        self.resolve_mcp_tool_name_collisions(all_agent_networks)

        return all_agent_networks

    def resolve_mcp_tool_name_collisions(self, all_agent_networks: Dict[str, Dict[str, AgentNetwork]]) -> None:
        """
        Makes sure no two public networks are advertised under the same MCP tool name.

        Tool names are derived from network names by replacing "/" with "__"
        (or come from an explicit "mcp_name" in the manifest), so distinct networks
        such as "a/b" and "a__b" can end up with the same tool name. MCP clients
        address tools by name alone, so one of the two has to stop being an MCP tool.
        The loser stays served over the regular APIs; only its MCP exposure is withdrawn.

        Every public network's own name is reserved as well, whether or not it is an
        MCP tool and whatever it is advertised as: a client that has not seen
        tools/list (or predates the rename) addresses a network by that name, and
        McpToolsProcessor passes it through to the network. Letting "a/b" be
        advertised as "a__b" while a network named "a__b" exists would route such
        calls to the wrong network, or answer them instead of refusing them when
        "a__b" is not an MCP tool.

        :param all_agent_networks: a nested map of storage type -> (mapping of name -> agent networks),
                                   modified in place for any losing network.
        """
        public_networks: Dict[str, AgentNetwork] = all_agent_networks.get(StorageClass.PUBLIC, {})
        if not public_networks:
            return

        # Map of tool name -> network name currently holding it.
        owners: Dict[str, str] = {}

        # Sorted so the outcome does not depend on manifest or dict ordering
        # between server restarts.
        for network_name in sorted(public_networks.keys()):
            agent_network: AgentNetwork = public_networks.get(network_name)
            # ServedManifestConfigFilter has already dropped None entries, but this
            # method is also callable on its own, so stay defensive.
            if agent_network is None:
                continue

            # Every network claims its own name (see above); an MCP network also
            # claims its advertised name when that differs. The own name goes first
            # so that if the advertised name loses below, the reservation stands.
            # A network whose only claim is its own name can never lose, so
            # clear_mcp_tool() is never called on a non-MCP network.
            claims: List[str] = [network_name]
            if agent_network.is_mcp_tool():
                tool_name: str = agent_network.get_mcp_tool_name()
                if tool_name != network_name:
                    claims.append(tool_name)

            for claim in claims:
                if claim not in owners:
                    owners[claim] = network_name
                    continue
                self.resolve_one_mcp_tool_name_collision(public_networks, owners, claim, network_name)

    def resolve_one_mcp_tool_name_collision(self, public_networks: Dict[str, AgentNetwork],
                                            owners: Dict[str, str],
                                            tool_name: str,
                                            contender_name: str) -> None:
        """
        Decides which of two networks keeps a contested MCP tool name and withdraws the other.

        :param public_networks: mapping of network name -> AgentNetwork for the public storage class
        :param owners: mapping of tool name -> network name currently holding it; updated in place
                       when the contender wins.
        :param tool_name: The contested MCP tool name
        :param contender_name: The network name that also wants tool_name, found after the current owner
        """
        owner_name: str = owners.get(tool_name)

        # Prefer the network whose tool name is its own network name unchanged.
        # That one was never renamed, so clients that already address it by that
        # name keep working, and the collision is attributable to the other
        # network's rename (or its explicit mcp_name), which the manifest author
        # can fix with a different mcp_name. Otherwise the first one seen keeps it.
        loser_name: str = contender_name
        if tool_name == contender_name and tool_name != owner_name:
            loser_name = owner_name
            owners[tool_name] = contender_name

        # Whoever owners now points at is the winner.
        winner_name: str = owners.get(tool_name)

        loser: AgentNetwork = public_networks.get(loser_name)
        loser.clear_mcp_tool()

        self.logger.error("MCP tool name '%s' is claimed by both network '%s' and network '%s'. " +
                          "Keeping it for '%s'; '%s' will not be served as an MCP tool. " +
                          "Give one of them a distinct \"mcp_name\" in its manifest entry to resolve this.",
                          tool_name, owner_name, contender_name, winner_name, loser_name)

    # pylint: disable=too-many-locals
    def restore_one_manifest(self, manifest_file: str) -> Dict[str, Dict[str, AgentNetwork]]:
        """
        :param manifest_file: The file reference to use when restoring.
        :return: a nested map of storage type -> (mapping of name -> agent networks)
        """
        start: float = perf_counter()

        agent_networks: Dict[str, Dict[str, AgentNetwork]] = {}
        for storage_class in StorageClass.ALL_PERMANENT:
            agent_networks[storage_class] = {}

        raw_restorer = RawManifestRestorer()
        raw_manifest: Dict[str, Any] = raw_restorer.restore(file_reference=manifest_file)

        if not raw_manifest:
            # Return early if no file and/or nothing in file
            self.logger.warning("Manifest file %s did not exist or was essentially empty.", manifest_file)
            return agent_networks

        # By the end of the filter chain, only served entries will be included.
        manifest_filter = ManifestFilterChain(manifest_file)
        one_manifest: Dict[str, Dict[str, Any]] = manifest_filter.filter_config(raw_manifest)

        file_of_class = FileOfClass(manifest_file)
        manifest_dir: str = file_of_class.get_basis()

        external_network_names: List[str] = self.find_external_network_names(one_manifest)

        # Determine how many threads to use and which style of executor to use
        if not one_manifest:
            return agent_networks

        # Avoid spawning an unbounded number of workers.
        my_cpu_count: int = cpu_count() or 1
        max_workers: int = min(len(one_manifest), my_cpu_count)

        # The default of "thread" is the least heavyweight, but not necessarily the fastest
        # given the context of how/how often the manifest is read.
        concurrency_context: str = environ.get("AGENT_MANIFEST_CONCURRENCY_CONTEXT", "thread")

        try:
            executor_factory = self.find_executory_factory(concurrency_context, max_workers)
            with executor_factory() as executor:

                read_one: Any = partial(self.read_one_agent_network,
                                        manifest_file=manifest_file,
                                        manifest_dir=manifest_dir,
                                        external_network_names=external_network_names,
                                        agent_mapper=self.agent_mapper)
                manifest_keys: List[str] = list(one_manifest.keys())
                manifest_dicts: List[Dict[str, Any]] = list(one_manifest.values())

                results: List[Tuple[AgentNetwork, str, Dict[str, Any]]] = executor.map(read_one, manifest_keys,
                                                                                       manifest_dicts)
                result: Tuple[AgentNetwork, str, Dict[str, Any]] = None
                for result in results:
                    self.maybe_store_agent_network(result[0], result[1], result[2], agent_networks)
        except Exception:     # pylint: disable=broad-except
            sensitive_logger = SensitiveLogger(self.logger)
            sensitive_logger.exception("Manifest file %s could not be restored.", manifest_file)

        stop: float = perf_counter()
        duration: float = stop - start
        if duration > 5.0:
            # DEF - for some reason infos don't show up in the logs at server start time. :shrug:
            self.logger.warning("Manifest file %s restored in %.2f seconds.", manifest_file, duration)

        return agent_networks

    def find_executory_factory(self, concurrency_context: str, max_workers: int) -> Any:
        """
        :param concurrency_context: The concurrency context to use.
        :param max_workers: The maximum number of workers to use.
        :return: The executor factory to use as a no-args constructor.
        """
        executor_factory = None
        lower_concurrency_context = concurrency_context.strip().lower()

        if lower_concurrency_context in ("spawn", "fork", "forkserver"):
            # Use a ProcessPoolExecutor for "spawn" and "fork".
            # In cases of large manifests, a ProcessPoolExecutor ends up being more heavyweight,
            # yet still more time-efficient because of the parallelism sidestepping the GIL.
            # When we get to free-threading in Python 3.14T, this can be all be changed back to ThreadPoolExecutor.
            #
            # "spawn" is the safest option (avoiding deadlocks) for environments where the manifest is changing,
            # but some speed is still desired (like development servers).
            #
            # "fork" is actually the fastest option, but has potential to lead to deadlocks.
            # This is still a reasonable option for server environments where the manifest
            # is known never to change at all.
            #
            # "forkserver" is a little slower than "fork" but with a bit more safety.
            # See https://docs.python.org/3/library/multiprocessing.html#contexts-and-start-methods
            # for more details.
            executor_factory = partial(ProcessPoolExecutor, max_workers=max_workers,
                                       mp_context=get_context(lower_concurrency_context))
        elif lower_concurrency_context == "thread":
            # Use a ThreadPoolExecutor for "thread".
            # The default of "thread" is best for servers who know their manifest content will be
            # changing over the course of their lifetime. It is slowest of all options, but has
            # the least amount of overall memory overhead and is lightweight and safe and problem-free.
            executor_factory = partial(ThreadPoolExecutor, max_workers=max_workers)
        else:
            # Default to ThreadPoolExecutor
            self.logger.warning("Unknown concurrency context '%s'. Defaulting to ThreadPoolExecutor.",
                                lower_concurrency_context)
            executor_factory = partial(ThreadPoolExecutor, max_workers=max_workers)

        return executor_factory

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    @staticmethod
    def read_one_agent_network(
                manifest_key: str,
                manifest_dict: Dict[str, Any],
                manifest_file: str = None,
                manifest_dir: str = None,
                external_network_names: List[str] = None,
                agent_mapper: AgentFileTreeMapper = None
            ) -> Tuple[AgentNetwork, str, Dict[str, Any]]:
        """
        :param manifest_dir: The directory of the manifest file.
        :param manifest_file: The file reference to use when restoring.
        :param manifest_key: The key in the manifest file.
        :param manifest_dict: The dictionary of the manifest file.
        :param external_network_names: The list of external network names
        :param agent_mapper: The AgentFileTreeMapper to use
        :return: A tuple of (agent_network, network_name, manifest_dict)
        """
        usable_network: bool = isinstance(manifest_dict, dict) and manifest_dict.get("serve", False)

        # We'll need to use an agent mapper to get to this agent definition file.
        agent_filepath: str = agent_mapper.agent_name_to_filepath(manifest_key)
        network_name: str = agent_mapper.filepath_to_agent_network_name(agent_filepath)
        validator = ManifestNetworkValidator(external_network_names, network_name=network_name)

        agent_network: AgentNetwork = None

        try:
            if usable_network:
                agent_network = RegistryManifestRestorer.restore_one_agent_network(
                    manifest_dir, agent_filepath, manifest_key, agent_mapper
                )

            agent_network = RegistryManifestRestorer.process_one_agent_network(
                agent_network, usable_network, agent_filepath,
                manifest_file, manifest_key, manifest_dict,
                validator, agent_mapper
            )
        except Exception as ex:     # pylint: disable=broad-except
            # None-out the agent_network.
            # This will mean that the failed read will skip the network without blowing anything else up.
            agent_network = None
            sensitive_logger = SensitiveLogger(getLogger(__name__))
            sensitive_logger.error("Failed to restore agent_network %s from %s. Skipping. - %s",
                                   manifest_key, manifest_file, str(ex))

        return agent_network, network_name, manifest_dict

    def maybe_store_agent_network(self, agent_network: AgentNetwork, network_name: str, manifest_dict: Dict[str, Any],
                                  agent_networks: Dict[str, Dict[str, AgentNetwork]]):
        """
        Determine whether and where to store the agent network

        :param agent_network: The agent network to store
        :param network_name: The name of the network
        :param manifest_dict: The manifest dictionary
        :param agent_networks: a nested map of storage type -> (mapping of name -> agent networks)
                                potentially modified
        """
        if agent_network is None and isinstance(manifest_dict, dict) and manifest_dict.get("serve", False):
            # Restore/validation failure - never stored, same as before
            return

        # At this point even if agent_network is None, we still have a store to do.
        # With a None agent_network, we just don't store anythin so a later manifest version
        # can override an earlier one, per ServerdManifiestConfigFilter.

        # Figure out where we want to put the network per the network's manifest dictionary
        storage: str = StorageClass.PUBLIC
        if not manifest_dict.get(StorageClass.PUBLIC):
            storage = StorageClass.PROTECTED
        if manifest_dict.get("periodic", False):
            self.periodic_configs[network_name] = manifest_dict["periodic"]

        agent_networks[storage][network_name] = agent_network

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    @staticmethod
    def process_one_agent_network(
                agent_network: AgentNetwork,
                usable_network: bool,
                agent_filepath: str,
                manifest_file: str,
                manifest_key: str,
                manifest_dict: Dict[str, Any],
                validator: ManifestNetworkValidator,
                agent_mapper: AgentFileTreeMapper
            ) -> AgentNetwork:
        """
        :param agent_network: The agent network to process.
        :param usable_network: Is this agent network usable?
        :param agent_filepath: The filepath to the agent definition file.
        :param manifest_file: The manifest file.
        :param manifest_key: The manifest key.
        :param manifest_dict: The manifest dictionary.
        :param validator: The validator.
        :param agent_mapper: The agent mapper.
        :return: The agent network
        """
        network_name: str = agent_mapper.filepath_to_agent_network_name(agent_filepath)
        logger: Logger = getLogger(__name__)

        if agent_network is not None:
            logger.info("Validating %s agent network...", network_name)
            validation_errors: List[str] = validator.validate(agent_network.get_config())
            if len(validation_errors) > 0:
                logger.error("manifest registry %s has validation errors. Skipping. Errors: %s",
                             agent_filepath,
                             json.dumps(validation_errors, indent=4, sort_keys=True))
                agent_network = None
                return agent_network

        if usable_network and agent_network is None:
            logger.error("manifest registry %s not found in %s", manifest_key, manifest_file)
            return agent_network

        # Check if this agent network has been declared as MCP tool:
        if usable_network and manifest_dict.get("mcp", False):
            tool_name: str = RegistryManifestRestorer.derive_mcp_tool_name(network_name, manifest_dict)
            agent_network.set_as_mcp_tool(tool_name)

        return agent_network

    @staticmethod
    def derive_mcp_tool_name(network_name: str, manifest_dict: Dict[str, Any]) -> str:
        """
        Works out the name an MCP-enabled network is advertised under as a tool.

        An explicit "mcp_name" in the manifest entry wins. Otherwise the name is
        derived from the network name by McpToolNamePolicy, so the "/" that
        registry sub-directories put into network names never reaches LLM
        providers (OpenAI, Anthropic) that reject it in tool names.

        Problems are warned about rather than refused: lenient clients such as
        local models still accept unusual names, so refusing to expose the tool
        would be a regression for them.

        :param network_name: The network name, used as the derivation basis and in log lines
        :param manifest_dict: The (already filtered) manifest dictionary for the network
        :return: The tool name to advertise. Never None or empty for a non-empty network_name.
        """
        logger: Logger = getLogger(__name__)

        # The policy is stateless, and this method sits on the static
        # restore_one_agent_network() chain, so a local instance is the
        # simplest way to reach the default McpToolNameFilter mapping.
        policy: McpToolNamePolicy = McpToolNamePolicy()
        tool_name: str = manifest_dict.get("mcp_name")
        if not tool_name:
            tool_name = policy.filter(network_name)

        if not policy.is_valid_tool_name(tool_name):
            logger.warning("MCP tool name '%s' for network '%s' does not match %s, which OpenAI and " +
                           "Anthropic require of tool names. Exposing it anyway; clients using those " +
                           "providers will fail to call it. Set a conforming \"mcp_name\" in the manifest.",
                           tool_name, network_name, McpToolNamePolicy.TOOL_NAME_PATTERN)

        if policy.is_over_soft_limit(tool_name):
            logger.warning("MCP tool name '%s' for network '%s' is longer than %d characters, " +
                           "which is OpenAI's limit for tool names. Exposing it anyway; consider a " +
                           "shorter \"mcp_name\" in the manifest.",
                           tool_name, network_name, McpToolNamePolicy.SOFT_MAX_LENGTH)

        return tool_name

    @staticmethod
    def restore_one_agent_network(manifest_dir: str, agent_filepath: str, manifest_key: str,
                                  agent_mapper: AgentFileTreeMapper) -> AgentNetwork:
        """
        :param manifest_dir: The directory of the manifest file
        :param agent_filepath: The file reference for the agent network description to restore
        :param manifest_key: the key to use when restoring
        :param agent_mapper: the agent mapper
        :return: a built map of agent networks
        """

        agent_network: AgentNetwork = None
        registry_restorer = AgentNetworkRestorer(registry_dir=manifest_dir, agent_mapper=agent_mapper)
        try:
            agent_network = registry_restorer.restore(file_reference=agent_filepath)
        except FileNotFoundError as exception:
            message: str = f"Failed to restore registry item {manifest_key}. Skipping. - {str(exception)}"
            sensitive_logger = SensitiveLogger(getLogger(__name__))
            sensitive_logger.error(message)
            agent_network = None
        except (ParseException, ParseSyntaxException, JSONDecodeError, ValueError) as exception:
            # ValueError is the wrapper type raised by AbstractAsyncConfigRestorer for any
            # parse / substitution / config-load failure; the other types are kept for
            # belt-and-suspenders in case a future code path raises one directly.

            # Be sure we spit out the right exception message with relevant parsing
            # information as the error.  If not, we don't get enough good information
            # to act on when there is a problem.
            use_exception: Exception = exception
            if exception.__cause__ is not None:
                use_exception = exception.__cause__

            message: str = f"Parse error in registry item {manifest_key}. Skipping. - {str(use_exception)}"
            sensitive_logger = SensitiveLogger(getLogger(__name__))
            sensitive_logger.error(message)
            agent_network = None

        return agent_network

    def restore(self, file_reference: str = None) -> Dict[str, Dict[str, AgentNetwork]]:
        """
        :param file_reference: The file reference to use when restoring.
                Default is None, implying the file reference is up to the
                implementation.
        :return: a nested map of storage type -> (mapping of name -> agent networks)
        """
        # Reset the periodic configs
        self.periodic_configs = {}

        if file_reference is not None:
            return self.restore_from_files([file_reference])

        agent_networks: Dict[str, Dict[str, AgentNetwork]] = self.restore_from_files(self.manifest_files)
        return agent_networks

    def get_manifest_files(self) -> List[str]:
        """
        Return current list of manifest files.
        """
        return self.manifest_files

    def find_external_network_names(self, manifest_entries: Dict[str, Any]) -> List[str]:
        """
        Find the list of valid external agent network names

        :param manifest_entries: The manifest entries
        :return: A list of valid external network references.
        """

        external_network_names: List[str] = []
        for manifest_key in manifest_entries.keys():

            # We'll need to use an agent mapper to get to this agent definition file.
            agent_filepath: str = self.agent_mapper.agent_name_to_filepath(manifest_key)
            network_name: str = self.agent_mapper.filepath_to_agent_network_name(agent_filepath)
            external_network_names.append(f"/{network_name}")

        return external_network_names

    def get_periodic_configs(self) -> Dict[str, Dict[str, Any]]:
        """
        :return: a map of agent name -> periodic config
        """
        return self.periodic_configs
