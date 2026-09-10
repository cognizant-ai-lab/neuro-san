
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

from pathlib import Path
from pathlib import PurePosixPath

from neuro_san.internals.interfaces.agent_name_mapper import AgentNameMapper


class AgentStandaloneMapper(AgentNameMapper):
    """
    A simple policy implementation defining conversion
    between agent name and agent standalone definition file
    (not specified relative to registry manifest root)
    """
    def __init__(self, path_method: Any = Path):
        """
        Constructor

        :param path_method: Optional Path method to use for path manipulations.
            Default is pathlib.Path, but can be overridden for testing purposes.
        """
        self.path_method: Any = path_method

    def agent_name_to_filepath(self, agent_name: str) -> str:
        """
        Agent name is its filepath.
        """
        return str(self.path_method(PurePosixPath(agent_name)))

    def filepath_to_agent_network_name(self, filepath: str) -> str:
        """
        Converts a file path to agent standalone definition file
        to agent network name identifying it to the service.
        """
        # Take the file name only - with no file path, and no file name extension:
        # /root/file_path/my_agent.hocon => my_agent
        return str(self.path_method(filepath).stem)
