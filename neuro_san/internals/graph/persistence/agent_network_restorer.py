
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

from pathlib import Path

from leaf_common.config.config_filter_chain import ConfigFilterChain

from neuro_san.internals.interfaces.agent_name_mapper import AgentNameMapper
from neuro_san.internals.graph.persistence.agent_filetree_mapper import AgentFileTreeMapper
from neuro_san.internals.graph.persistence.agent_standalone_mapper import AgentStandaloneMapper
from neuro_san.internals.graph.filters.defaults_config_filter import DefaultsConfigFilter
from neuro_san.internals.graph.filters.dictionary_common_defs_config_filter \
    import DictionaryCommonDefsConfigFilter
from neuro_san.internals.graph.filters.name_correction_config_filter import NameCorrectionConfigFilter
from neuro_san.internals.graph.filters.string_common_defs_config_filter import StringCommonDefsConfigFilter
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.persistence.abstract_async_config_restorer import AbstractAsyncConfigRestorer


class AgentNetworkRestorer(AbstractAsyncConfigRestorer):
    """
    Implementation of the AbstractAsyncConfigRestorer interface to read in an AgentNetwork
    instance given a JSON file name.
    """

    def __init__(self, registry_dir: str = None, agent_mapper: AgentNameMapper = None):
        """
        Constructor

        :param registry_dir: The directory under which file_references
                    for registry files are allowed to be found.
                    If None, there are no limits, but paths must be absolute
        :param agent_mapper: optional AgentNameMapper;
            if None, default will be used:
                if registry_dir is None, AgentStandaloneMapper instance will be used;
                otherwise, we use AgentFileTreeMapper.
        """
        super().__init__(file_purpose="agent network", must_exist=True)

        self.registry_dir: str = registry_dir
        self.agent_mapper = agent_mapper
        if not self.agent_mapper:
            if self.registry_dir is not None:
                self.agent_mapper = AgentFileTreeMapper()
            else:
                self.agent_mapper = AgentStandaloneMapper()

    def get_file_path(self, file_reference: str = None) -> str:
        """
        :param file_reference: The file reference to use when restoring.
                Default is None, implying the file reference is up to the
                implementation.
        :return: an string of the file path to use
        """
        if file_reference is None or len(file_reference) == 0:
            raise ValueError(f"file_reference {file_reference} cannot be None or empty string")

        use_file: str = file_reference
        if self.registry_dir is not None:
            # This should be OS-agnostic operation, producing a valid local file path
            use_file = str(Path(self.registry_dir) / file_reference)

        return use_file

    def restore(self, file_reference: str = None) -> AgentNetwork:
        """
        Synchronous restore from the given file reference.
        :param file_reference: The file reference to use when restoring.
                Default is None, implying the file reference is up to the
                implementation.
        :return: an AgentNetwork.
        """
        config: Dict[str, Any] = super().restore(file_reference)
        return self.create_network(config, file_reference)

    async def async_restore(self, file_reference: str = None) -> AgentNetwork:
        """
        Asynchronous restore from the given file reference.
        :param file_reference: The file reference to use when restoring.
                Default is None, implying the file reference is up to the
                implementation.
        :return: an AgentNetwork.
        """
        config: Dict[str, Any] = await super().async_restore(file_reference)
        return self.create_network(config, file_reference)

    def create_network(self, config: Dict[str, Any], file_reference: str) -> AgentNetwork:
        """
        :param config: agent configuration dictionary, built or parsed from external sources
        :param file_reference: The file reference used for restoring
        :return: AgentNetwork instance for an agent.
        """
        if config is None:
            return None

        # Inside here is incorrectly flagged as destination of Path Traversal 7
        #   Reason: The lines above ensure that the path of registry_dir is within
        #           this source base. CheckMarx does not recognize
        #           the calls to Pathlib/__file__ as a valid means to resolve
        #           these kinds of issues.
        name: str = self.agent_mapper.filepath_to_agent_network_name(file_reference)

        # Now create the AgentNetwork
        agent_network = AgentNetwork(config, name)
        return agent_network

    def filter_config(self, basis_config: Dict[str, Any], file_path: str = None) -> Dict[str, Any]:
        """
        :param basis_config: agent configuration dictionary, built or parsed from external sources
        :return: An agent network dictionary that has gone through the standard filter chain.
        """
        # Perform a filter chain on the config that was read in
        filter_chain = ConfigFilterChain()
        filter_chain.register(DictionaryCommonDefsConfigFilter())
        filter_chain.register(StringCommonDefsConfigFilter())
        filter_chain.register(DefaultsConfigFilter())
        filter_chain.register(NameCorrectionConfigFilter())

        config: Dict[str, Any] = filter_chain.filter_config(basis_config)
        return config
