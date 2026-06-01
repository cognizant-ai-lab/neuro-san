
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
from typing import Union

import os
import json
import logging

from json.decoder import JSONDecodeError
from pyparsing.exceptions import ParseException
from pyparsing.exceptions import ParseSyntaxException

from leaf_common.config.config_filter import ConfigFilter
from leaf_common.config.dictionary_overlay import DictionaryOverlay
from leaf_common.config.file_of_class import FileOfClass
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
        self.agent_mapper = agent_mapper
        if not self.agent_mapper:
            self.agent_mapper = AgentFileTreeMapper()

        self.manifest_files: List[str] = []
        self.periodic_configs: Dict[str, Dict[str, Any]] = {}

        if manifest_files is None:
            # We have no manifest list coming in, so check an env variable for a definition.
            manifest_file: str = os.environ.get("AGENT_MANIFEST_FILE")
            if manifest_file is None:
                # No env var, so fallback to what is coded in this repo.
                manifest_file = REGISTRIES_DIR.get_file_in_basis("manifest.hocon")

            # Add what was found above
            use_files: List[str] = manifest_file.split(" ")
            self.manifest_files.extend(use_files)
        elif isinstance(manifest_files, str):
            use_files: List[str] = manifest_files.split(" ")
            self.manifest_files.extend(use_files)
        else:
            self.manifest_files = manifest_files

        self.logger = logging.getLogger(self.__class__.__name__)

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

        return all_agent_networks

    async def async_restore_from_files(self, file_references: Sequence[str]) -> Dict[str, Dict[str, AgentNetwork]]:
        """
        :param file_references: The sequence of file references to use when restoring.
        :return: a nested map of storage type -> (mapping of name -> agent networks)
        """

        all_agent_networks: Dict[str, Dict[str, AgentNetwork]] = {}
        overlayer = DictionaryOverlay()

        # Loop through all the manifest files in the list to make a composite
        for manifest_file in file_references:
            agents_from_one_manifest: Dict[str, Dict[str, AgentNetwork]] = \
                await self.async_restore_one_manifest(manifest_file)
            # Do a deep update() with the overlayer.
            all_agent_networks = overlayer.overlay(all_agent_networks, agents_from_one_manifest)

        # Loop through the agent networks dictionary removing any references to None values
        # for networks. This indicates they should not be served.
        config_filter: ConfigFilter = ServedManifestConfigFilter(manifest_file=None,
                                                                 warn_on_skip=False,
                                                                 entry_for_skipped=False)
        for storage_type, storage_dict in all_agent_networks.items():
            all_agent_networks[storage_type] = config_filter.filter_config(storage_dict)

        return all_agent_networks

    # pylint: disable=too-many-locals
    def restore_one_manifest(self, manifest_file: str) -> Dict[str, Dict[str, AgentNetwork]]:
        """
        :param manifest_file: The file reference to use when restoring.
        :return: a nested map of storage type -> (mapping of name -> agent networks)
        """

        agent_networks: Dict[str, Dict[str, AgentNetwork]] = {}
        for storage_class in StorageClass.ALL_PERMANENT:
            agent_networks[storage_class] = {}

        raw_restorer = RawManifestRestorer()
        raw_manifest: Dict[str, Any] = raw_restorer.restore(file_reference=manifest_file)

        # By the end of the filter chain, only served entries will be included.
        manifest_filter = ManifestFilterChain(manifest_file)
        one_manifest: Dict[str, Dict[str, Any]] = manifest_filter.filter_config(raw_manifest)

        file_of_class = FileOfClass(manifest_file)
        manifest_dir: str = file_of_class.get_basis()

        external_network_names: List[str] = self.find_external_network_names(one_manifest)

        # DEF - need mcp servers as well at some point
        validator = ManifestNetworkValidator(external_network_names)

        # At this point only hocon files we are going to serve up are in the one_manifest.
        for manifest_key, manifest_dict in one_manifest.items():

            usable_network: bool = isinstance(manifest_dict, dict) and manifest_dict.get("serve", False)

            # We'll need to use an agent mapper to get to this agent definition file.
            agent_filepath: str = self.agent_mapper.agent_name_to_filepath(manifest_key)
            agent_network: AgentNetwork = None
            if usable_network:
                agent_network = self.restore_one_agent_network(manifest_dir, agent_filepath, manifest_key)

            self.process_one_agent_network(agent_network, usable_network, agent_filepath,
                                           manifest_file, manifest_key, manifest_dict,
                                           validator, agent_networks)

        return agent_networks

    # pylint: disable=too-many-locals
    async def async_restore_one_manifest(self, manifest_file: str) -> Dict[str, Dict[str, AgentNetwork]]:
        """
        :param manifest_file: The file reference to use when restoring.
        :return: a nested map of storage type -> (mapping of name -> agent networks)
        """

        agent_networks: Dict[str, Dict[str, AgentNetwork]] = {}
        for storage_class in StorageClass.ALL_PERMANENT:
            agent_networks[storage_class] = {}

        raw_restorer = RawManifestRestorer()
        raw_manifest: Dict[str, Any] = await raw_restorer.async_restore(file_reference=manifest_file)

        # By the end of the filter chain, only served entries will be included.
        manifest_filter = ManifestFilterChain(manifest_file)
        one_manifest: Dict[str, Dict[str, Any]] = manifest_filter.filter_config(raw_manifest)

        file_of_class = FileOfClass(manifest_file)
        manifest_dir: str = file_of_class.get_basis()

        external_network_names: List[str] = self.find_external_network_names(one_manifest)

        # DEF - need mcp servers as well at some point
        validator = ManifestNetworkValidator(external_network_names)

        # At this point only hocon files we are going to serve up are in the one_manifest.
        for manifest_key, manifest_dict in one_manifest.items():

            usable_network: bool = isinstance(manifest_dict, dict) and manifest_dict.get("serve", False)

            # We'll need to use an agent mapper to get to this agent definition file.
            agent_filepath: str = self.agent_mapper.agent_name_to_filepath(manifest_key)
            agent_network: AgentNetwork = None
            if usable_network:
                agent_network = await self.async_restore_one_agent_network(manifest_dir, agent_filepath, manifest_key)

            self.process_one_agent_network(agent_network, usable_network, agent_filepath,
                                           manifest_file, manifest_key, manifest_dict,
                                           validator, agent_networks)

        return agent_networks

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def process_one_agent_network(self, agent_network: AgentNetwork, usable_network: bool, agent_filepath: str,
                                  manifest_file: str, manifest_key: str, manifest_dict: Dict[str, Any],
                                  validator: ManifestNetworkValidator,
                                  agent_networks: Dict[str, Dict[str, AgentNetwork]]):
        """
        :param agent_network: The agent network to process.
        :param usable_network: Is this agent network usable?
        :param agent_filepath: The filepath to the agent definition file.
        :param manifest_file: The manifest file.
        :param manifest_key: The manifest key.
        :param manifest_dict: The manifest dictionary.
        :param validator: The validator.
        :param agent_networks: The accumulated agent networks
        """
        if agent_network is not None:

            validation_errors: List[str] = validator.validate(agent_network.get_config())
            if len(validation_errors) > 0:
                self.logger.error("manifest registry %s has validation errors. Skipping. Errors: %s",
                                  agent_filepath,
                                  json.dumps(validation_errors, indent=4, sort_keys=True))
                agent_network = None
                return

        if usable_network and agent_network is None:
            self.logger.error("manifest registry %s not found in %s", manifest_key, manifest_file)
            return

        network_name: str = self.agent_mapper.filepath_to_agent_network_name(agent_filepath)

        # Check if this agent network has been declared as MCP tool:
        if usable_network and manifest_dict.get("mcp", False):
            agent_network.set_as_mcp_tool()

        # Figure out where we want to put the network per the network's manifest dictionary
        storage: str = StorageClass.PUBLIC
        if not manifest_dict.get(StorageClass.PUBLIC):
            storage = StorageClass.PROTECTED
        if manifest_dict.get("periodic", False):
            self.periodic_configs[network_name] = manifest_dict["periodic"]

        agent_networks[storage][network_name] = agent_network

    def restore_one_agent_network(self, manifest_dir: str, agent_filepath: str, manifest_key: str) -> AgentNetwork:
        """
        :param manifest_dir: The directory of the manifest file
        :param agent_filepath: The file reference for the agent network description to restore
        :param manifest_key: the key to use when restoring
        :return: a built map of agent networks
        """

        agent_network: AgentNetwork = None
        registry_restorer = AgentNetworkRestorer(registry_dir=manifest_dir, agent_mapper=self.agent_mapper)
        try:
            agent_network = registry_restorer.restore(file_reference=agent_filepath)
        except FileNotFoundError as exception:
            message: str = f"Failed to restore registry item {manifest_key}. Skipping. - {str(exception)}"
            self.logger.error(message)
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
            self.logger.error(message)
            agent_network = None

        return agent_network

    async def async_restore_one_agent_network(self, manifest_dir: str, agent_filepath: str, manifest_key: str) \
            -> AgentNetwork:
        """
        :param manifest_dir: The directory of the manifest file
        :param agent_filepath: The file reference for the agent network description to restore
        :param manifest_key: the key to use when restoring
        :return: a built map of agent networks
        """

        agent_network: AgentNetwork = None
        registry_restorer = AgentNetworkRestorer(registry_dir=manifest_dir, agent_mapper=self.agent_mapper)
        try:
            agent_network = await registry_restorer.async_restore(file_reference=agent_filepath)
        except FileNotFoundError as exception:
            message: str = f"Failed to restore registry item {manifest_key}. Skipping. - {str(exception)}"
            self.logger.error(message)
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
            self.logger.error(message)
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

    async def async_restore(self, file_reference: str = None) -> Dict[str, Dict[str, AgentNetwork]]:
        """
        :param file_reference: The file reference to use when restoring.
                Default is None, implying the file reference is up to the
                implementation.
        :return: a nested map of storage type -> (mapping of name -> agent networks)
        """
        # Reset the periodic configs
        self.periodic_configs = {}

        if file_reference is not None:
            return await self.async_restore_from_files([file_reference])

        agent_networks: Dict[str, Dict[str, AgentNetwork]] = await self.async_restore_from_files(self.manifest_files)
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
