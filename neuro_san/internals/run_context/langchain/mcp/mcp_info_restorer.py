
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

from logging import Logger
from logging import getLogger
import os
from typing import Any, Dict

import json
from pyparsing.exceptions import ParseException
from pyparsing.exceptions import ParseSyntaxException

from leaf_common.persistence.easy.easy_hocon_persistence import EasyHoconPersistence
from leaf_common.persistence.interface.restorer import Restorer


class McpInfoRestorer(Restorer):
    """
    Implementation of the Restorer interface that reads the MCP info file.
    The file path can be provided via the AGENT_MCP_INFO_FILE env var.
    The file can contain the following info for each MCP server:
    - MCP server url
    - server endpoints (e.g. authorization_endpoint, token endpoint, and timeout settings)
    - http headers
    - client info (e.g. client id, client secret, token_endpoint_auth_method, and scopes)
    - tool filtering info (e.g. allowed tools list)
    """

    def __init__(self):
        """
        Constructor
        """
        self.logger: Logger = getLogger(self.__class__.__name__)

    def restore(self, file_reference: str = None) -> Dict[str, Any]:
        """
        :param file_reference: The file reference to use when restoring.
                Default is None, implying the file reference is up to the
                implementation.
        :return: a dictionary with MCP servers information
        """
        file_path: str = file_reference
        if not file_path:
            # First check for AGENT_MCP_INFO_FILE env var, then fallback to MCP_SERVERS_INFO_FILE env var for
            # backward compatibility (will be removed in neuro-san==0.7)
            if os.getenv("AGENT_MCP_INFO_FILE"):
                file_path = os.environ.get("AGENT_MCP_INFO_FILE")
                self.logger.info("Restoring MCP info from file specified in AGENT_MCP_INFO_FILE env var: %s", file_path)
            elif os.getenv("MCP_SERVERS_INFO_FILE"):
                file_path = os.environ.get("MCP_SERVERS_INFO_FILE")
                self.logger.info(
                    "Restoring MCP info from file specified in MCP_SERVERS_INFO_FILE env var: %s", file_path)
                self.logger.warning(
                    "MCP_SERVERS_INFO_FILE env var is deprecated and will be removed in neuro-san==0.7. "
                    "Please switch to AGENT_MCP_INFO_FILE env var."
                )
            else:
                # No servers info file specified.
                return None

        servers_info: Dict[str, Any] = None
        if file_path.endswith(".hocon"):
            hocon = EasyHoconPersistence()
            try:
                servers_info = hocon.restore(file_reference=file_path)
            except (ParseException, ParseSyntaxException) as exception:
                message: str = f"""
        There was an error parsing MCP info file "{file_path}".
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
        There was an error parsing MCP info file "{file_path}".
        See the accompanying JSONDecodeError exception (above) for clues as to what might be
        syntactically incorrect in that file.
        """
                raise ParseException(message) from exception
        if servers_info is None:
            message = f"Could not find MCP info file at path: {file_path}.\n" + """
            Some common problems include:
            * The file itself simply does not exist.
            * Path is not an absolute path and you are invoking the server from a place
              where the path is not reachable.
            * The path has a typo in it.

            Double-check the value of the AGENT_MCP_INFO_FILE and MCP_SERVERS_INFO_FILE env var and
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
