
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
from typing import Optional

from neuro_san.internals.persistence.abstract_async_config_restorer import AbstractAsyncConfigRestorer


class McpServersInfoRestorer(AbstractAsyncConfigRestorer):
    """
    Implementation of the AbstractAsyncConfigRestorer that reads the MCP servers info file.
    The restore() and async_restore() methods both return a dictionary.

    NOTE: This class is highly experimental and implementation of MCP servers
    is very likely to change in future releases.
    """

    def __init__(self):
        # If the MCP info file does not exist, use values from the network HOCON file.
        super().__init__(file_purpose="MCP servers info", env_var="MCP_SERVERS_INFO_FILE", must_exist=False)

    def filter_config(self, basis_config: Dict[str, Any], file_path: str = None) -> Optional[Dict[str, Any]]:
        """
        :param basis_config: A dictionary with MCP servers information
        :param file_path: The path to the MCP servers info file
        :return: a dictionary with MCP servers information or None if there is no config (no file, or file not found)
        """

        # Basic file checking help in here
        basis_config: Optional[Dict[str, Any]] = super().filter_config(basis_config, file_path)

        # If there is no config (no file, or file not found), just return None to indicate that.
        if basis_config is None:
            return None

        # Now, MCP endpoints urls could put in quotes, so strip them out.
        result_dict: Dict[str, Any] = {}
        for key, value in basis_config.items():
            use_key: str = key.replace(r'"', "")
            use_key = use_key.strip()
            result_dict[use_key] = value

        return result_dict
