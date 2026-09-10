
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


class AgentFileTreeMapper(AgentNameMapper):
    """
    A simple policy implementation defining conversion
    between agent name as specified in a manifest file
    and a file path (relative to registry root directory) to this agent definition file.
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
        Converts an agent name from registry manifest to file path to this agent definition file.
        """
        # agent_name from registry manifest uses '/' as separator,
        # we need to convert it to the local OS file path format.
        return str(self.path_method(PurePosixPath(agent_name)))

    def filepath_to_agent_network_name(self, filepath: str) -> str:
        """
        Converts a file path to agent definition file (relative to registry root directory)
        to agent network name identifying it to the service.
        """
        # Remove file name extension, convert it to "/" separator.
        # Specifically:
        # self.path_method(filepath).as_posix() - converts to Path format we use (default is OS native)
        #     and then to posix format (with '/' separator). This gets us a string.
        # PurePosixPath(...).with_suffix("") - converts string to a posix path (with "/")
        #     and removes the file extension.
        # str(...) - converts back to string.
        return str(PurePosixPath(self.path_method(filepath).as_posix()).with_suffix(""))
