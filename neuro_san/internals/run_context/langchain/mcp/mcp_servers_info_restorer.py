
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

import os
from typing import Any, Dict

import json
from pyparsing.exceptions import ParseException
from pyparsing.exceptions import ParseSyntaxException

from leaf_common.persistence.easy.easy_hocon_persistence import EasyHoconPersistence
from leaf_common.persistence.interface.restorer import Restorer


class McpServersInfoRestorer(Restorer):
    """
    Implementation of the Restorer interface that reads the MCP servers info file.
    NOTE: This class is highly experimental and implementation of MCP servers
    is very likely to change in future releases.
    """

    def restore(self, file_reference: str = None) -> Dict[str, Any]:
        """
        :param file_reference: The file reference to use when restoring.
                Default is None, implying the file reference is up to the
                implementation.
        :return: a dictionary with MCP servers information
        """
        file_path: str = file_reference
        if not file_path:
            # "MCP_SERVERS_INFO_FILE" will be deprecated in neuro-san==0.7.
            file_path = os.environ.get("AGENT_MCP_SERVERS_INFO_FILE") or os.environ.get("MCP_SERVERS_INFO_FILE")
            if not file_path:
                # No servers info file specified.
                return None

        servers_info: Dict[str, Any] = None
        if file_path.endswith(".hocon"):
            hocon = EasyHoconPersistence()
            try:
                servers_info = hocon.restore(file_reference=file_path)
            except (ParseException, ParseSyntaxException) as exception:
                message: str = f"""
        There was an error parsing MCP servers info file "{file_path}".
        See the accompanying ParseException (above) for clues as to what might be
        syntactically incorrect in that file.
        """
                raise ParseException(message) from exception
        else:
            try:
                with open(file_path, "r", encoding="utf-8") as json_file:
                    servers_info = json.load(json_file)
            except FileNotFoundError:
                # Use the common verbiage below
                servers_info = None
            except json.decoder.JSONDecodeError as exception:
                message: str = f"""
        There was an error parsing MCP servers info file "{file_path}".
        See the accompanying JSONDecodeError exception (above) for clues as to what might be
        syntactically incorrect in that file.
        """
                raise ParseException(message) from exception
        if servers_info is None:
            message = f"Could not find MCP servers info file at path: {file_path}.\n" + """
            Some common problems include:
            * The file itself simply does not exist.
            * Path is not an absolute path and you are invoking the server from a place
              where the path is not reachable.
            * The path has a typo in it.

            Double-check the value of the MCP_SERVERS_INFO_FILE env var and
            your current working directory (pwd).
            """
            raise FileNotFoundError(message)
        # Now, MCP endpoints urls could put in quotes, so strip them out.
        result_dict: Dict[str, Any] = {}
        for key, value in servers_info.items():
            use_key: str = key.replace(r'"', "")
            use_key = use_key.strip()
            result_dict[use_key] = value
        return result_dict
