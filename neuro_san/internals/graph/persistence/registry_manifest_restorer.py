
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
from typing import List
from typing import Sequence
from typing import Union

import os
import json
import logging

from pathlib import Path
from pyparsing.exceptions import ParseException
from pyparsing.exceptions import ParseSyntaxException

from leaf_common.persistence.easy.easy_hocon_persistence import EasyHoconPersistence
from leaf_common.persistence.interface.restorer import Restorer

from neuro_san.internals.graph.persistence.agent_network_restorer import AgentNetworkRestorer
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.utils.file_of_class import FileOfClass


class RegistryManifestRestorer(Restorer):
    """
    Implementation of the Restorer interface that reads the manifest file
    for agent networks/registries.
    """

    def __init__(self, manifest_files: Union[str, List[str]] = None):
        """
        Constructor

        :param manifest_files: Either:
            * A single local name for the manifest file listing the agents to host.
            * A list of local names for multiple manifest files to host
            * None (the default) which gets a single manifest file from a known source.
        """
        self.manifest_files: List[str] = []

        if manifest_files is None:
            # We have no manifest list coming in, so check an env variable for a definition.
            manifest_file: str = os.environ.get("AGENT_MANIFEST_FILE")
            if manifest_file is None:
                # No env var, so fallback to whatis coded in this repo.
                file_of_class = FileOfClass(__file__, path_to_basis="../../../registries")
                manifest_file = file_of_class.get_file_in_basis("manifest.hocon")

            # Add what was found above
            self.manifest_files.append(manifest_file)
        elif isinstance(manifest_files, str):
            self.manifest_files.append(manifest_files)
        else:
            self.manifest_files = manifest_files

        self.logger = logging.getLogger(self.__class__.__name__)

    # pylint: disable=too-many-locals
    def restore_from_files(self, file_references: Sequence[str]) -> Dict[str, AgentNetwork]:
        """
        :param file_references: The sequence of file references to use when restoring.
        :return: a built map of agent networks
        """

        agent_networks: Dict[str, AgentNetwork] = {}

        # Loop through all the manifest files in the list to make a composite
        for manifest_file in file_references:

            one_manifest: Dict[str, Any] = {}
            if manifest_file.endswith(".hocon"):
                hocon = EasyHoconPersistence()
                try:
                    one_manifest = hocon.restore(file_reference=manifest_file)
                except (ParseException, ParseSyntaxException) as exception:
                    message: str = f"""
There was an error parsing the agent network manifest file "{manifest_file}".
See the accompanying ParseException (above) for clues as to what might be
syntactically incorrect in that file.
"""
                    raise ParseException(message) from exception
            else:
                try:
                    with open(manifest_file, "r", encoding="utf-8") as json_file:
                        one_manifest = json.load(json_file)
                except FileNotFoundError:
                    # Use the common verbiage below
                    one_manifest = None
                except json.decoder.JSONDecodeError as exception:
                    message: str = f"""
There was an error parsing the agent network manifest file "{manifest_file}".
See the accompanying JSONDecodeError exception (above) for clues as to what might be
syntactically incorrect in that file.
"""
                    raise ParseException(message) from exception

            if one_manifest is None:
                message = f"Could not find manifest file at path: {manifest_file}.\n" + """
Some common problems include:
* The file itself simply does not exist.
* Path is not an absolute path and you are invoking the server from a place
  where the path is not reachable.
* The path has a typo in it.

Double-check the value of the AGENT_MANIFEST_FILE env var and
your current working directory (pwd).
"""
                raise FileNotFoundError(message)

            for key, value in one_manifest.items():

                # Keys sometimes come with quotes.
                use_key: str = key.replace(r'"', "")

                if not bool(value):
                    continue

                file_of_class = FileOfClass(manifest_file)
                manifest_dir: str = file_of_class.get_basis()
                registry_restorer = AgentNetworkRestorer(manifest_dir)
                try:
                    agent_network: AgentNetwork = registry_restorer.restore(file_reference=use_key)
                except FileNotFoundError as exc:
                    self.logger.error("Failed to restore registry item %s - %s", use_key, str(exc))
                    agent_network = None
                if agent_network is not None:
                    network_name: str = Path(use_key).stem
                    agent_networks[network_name] = agent_network
                else:
                    self.logger.error("manifest registry %s not found in %s", use_key, manifest_file)

        return agent_networks

    # pylint: disable=too-many-locals
    def restore(self, file_reference: str = None) -> Dict[str, AgentNetwork]:
        """
        :param file_reference: The file reference to use when restoring.
                Default is None, implying the file reference is up to the
                implementation.
        :return: a built map of agent networks
        """
        if file_reference is not None:
            return self.restore_from_files([file_reference])

        agent_networks: Dict[str, AgentNetwork] =\
            self.restore_from_files(self.manifest_files)
        return agent_networks

    def get_manifest_files(self) -> List[str]:
        """
        Return current list of manifest files.
        """
        return self.manifest_files
