
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

import unittest
from pathlib import PurePosixPath, PureWindowsPath

from neuro_san.internals.graph.persistence.agent_filetree_mapper import AgentFileTreeMapper
from neuro_san.internals.graph.persistence.agent_standalone_mapper import AgentStandaloneMapper


class TestMapper(unittest.TestCase):
    """
    Tests different file mappers
    """

    def test_posix_mapping(self):
        """
        Tests mapping on POSIX platforms
        """
        mapper = AgentFileTreeMapper(PurePosixPath)

        manifest_entry = "folder/subfolder/agent_definition.hocon"
        agent_filepath = mapper.agent_name_to_filepath(manifest_entry)
        self.assertEqual(agent_filepath, r"folder/subfolder/agent_definition.hocon")

        agent_network = mapper.filepath_to_agent_network_name(agent_filepath)
        self.assertEqual(agent_network, r"folder/subfolder/agent_definition")

    def test_windows_mapping(self):
        """
        Tests mapping on Windows platforms
        """
        mapper = AgentFileTreeMapper(PureWindowsPath)

        manifest_entry = "folder/subfolder/agent_definition.hocon"
        agent_filepath = mapper.agent_name_to_filepath(manifest_entry)
        self.assertEqual(agent_filepath, r"folder\subfolder\agent_definition.hocon")

        agent_network = mapper.filepath_to_agent_network_name(agent_filepath)
        self.assertEqual(agent_network, r"folder/subfolder/agent_definition")

    def test_standalone_posix_mapping(self):
        """
        Tests mapping on POSIX platforms
        """
        mapper = AgentStandaloneMapper(PurePosixPath)

        file_entry = r"/folder/subfolder/agent_definition.hocon"
        agent_filepath = mapper.agent_name_to_filepath(file_entry)
        self.assertEqual(agent_filepath, r"/folder/subfolder/agent_definition.hocon")

        agent_network = mapper.filepath_to_agent_network_name(agent_filepath)
        self.assertEqual(agent_network, r"agent_definition")

    def test_standalone_windows_mapping(self):
        """
        Tests mapping on Windows platforms
        """
        mapper = AgentStandaloneMapper(PureWindowsPath)

        file_entry = r"C:\folder\subfolder\agent_definition.hocon"
        agent_filepath = mapper.agent_name_to_filepath(file_entry)
        self.assertEqual(agent_filepath, r"C:\folder\subfolder\agent_definition.hocon")

        agent_network = mapper.filepath_to_agent_network_name(agent_filepath)
        self.assertEqual(agent_network, r"agent_definition")
