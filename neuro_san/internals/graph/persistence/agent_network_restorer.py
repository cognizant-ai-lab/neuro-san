
# Copyright (C) 2023-2025 Cognizant Digital Business, Evolutionary AI.
# All Rights Reserved.
# Issued under the Academic Public License.
#
# You can be released from the terms, and requirements of the Academic Public
# License by purchasing a commercial license.
# Purchase of a commercial license is mandatory for any use of the
# neuro-san SDK Software in commercial settings.
#
# END COPYRIGHT

from typing import Any
from typing import Dict

from os import path
from pathlib import Path

import json

from pyparsing.exceptions import ParseException
from pyparsing.exceptions import ParseSyntaxException

from leaf_common.config.config_filter_chain import ConfigFilterChain
from leaf_common.persistence.easy.easy_hocon_persistence import EasyHoconPersistence
from leaf_common.persistence.interface.restorer import Restorer

from neuro_san.internals.graph.filters.defaults_config_filter import DefaultsConfigFilter
from neuro_san.internals.graph.filters.dictionary_common_defs_config_filter \
    import DictionaryCommonDefsConfigFilter
from neuro_san.internals.graph.filters.name_correction_config_filter import NameCorrectionConfigFilter
from neuro_san.internals.graph.filters.string_common_defs_config_filter \
    import StringCommonDefsConfigFilter
from neuro_san.internals.graph.registry.agent_network import AgentNetwork


class AgentNetworkRestorer(Restorer):
    """
    Implementation of the Restorer interface to read in an AgentNetwork
    instance given a JSON file name.
    """

    def __init__(self, registry_dir: str = None):
        """
        Constructor

        :param registry_dir: The directory under which file_references
                    for registry files are allowed to be found.
                    If None, there are no limits, but paths must be absolute
        """
        self.registry_dir: str = registry_dir

    def restore(self, file_reference: str = None):
        """
        :param file_reference: The file reference to use when restoring.
                Default is None, implying the file reference is up to the
                implementation.
        :return: an object from some persisted store
        """
        config: Dict[str, Any] = None

        if file_reference is None or len(file_reference) == 0:
            raise ValueError(f"file_reference {file_reference} cannot be None or empty string")

        use_file: str = file_reference
        if self.registry_dir is not None:
            use_file = path.join(self.registry_dir, file_reference)

        try:
            if use_file.endswith(".json"):
                config = json.load(use_file)
            elif use_file.endswith(".hocon"):
                hocon = EasyHoconPersistence(full_ref=use_file, must_exist=True)
                config = hocon.restore()
            else:
                raise ValueError(f"file_reference {use_file} must be a .json or .hocon file")
        except (ParseException, ParseSyntaxException, json.decoder.JSONDecodeError) as exception:
            message = f"""
There was an error parsing the agent network file "{use_file}".
See the accompanying ParseException (above) for clues as to what might be
syntactically incorrect in that file.
"""
            raise ParseException(message) from exception

        # Now create the AgentNetwork
        # Inside here is incorrectly flagged as destination of Path Traversal 7
        #   Reason: The lines above ensure that the path of registry_dir is within
        #           this source base. CheckMarx does not recognize
        #           the calls to Pathlib/__file__ as a valid means to resolve
        #           these kinds of issues.
        name = Path(use_file).stem
        agent_network: AgentNetwork = self.restore_from_config(name, config)
        return agent_network

    def restore_from_config(self, agent_name: str, config: Dict[str, Any]) -> AgentNetwork:
        """
        :param agent_name: name of an agent;
        :param config: agent configuration dictionary,
            built or parsed from external sources;
        :return: AgentNetwork instance for an agent.
        """
        # Perform a filter chain on the config that was read in
        filter_chain = ConfigFilterChain()
        filter_chain.register(DictionaryCommonDefsConfigFilter())
        filter_chain.register(StringCommonDefsConfigFilter())
        filter_chain.register(DefaultsConfigFilter())
        filter_chain.register(NameCorrectionConfigFilter())
        config = filter_chain.filter_config(config)

        # Now create the AgentNetwork
        agent_network = AgentNetwork(config, agent_name)

        return agent_network
