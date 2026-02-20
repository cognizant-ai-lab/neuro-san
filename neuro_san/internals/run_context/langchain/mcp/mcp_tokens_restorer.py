
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
from typing import Any
from typing import Dict
from typing import Optional

import json
from pyparsing.exceptions import ParseException

from leaf_common.persistence.interface.restorer import Restorer


class McpTokensRestorer(Restorer):
    """
    Implementation of the Restorer interface that reads the tokens info from environment variable,
    AGENT_MCP_TOKENS. The env var should be in the following format:
    '{"https://example.com/mcp": {"access_token": "eyJhbG...", "expires_in": 3600, "refresh_token": "def502..."}}'
    Note that MCP SDK only support bearer token so it is not necessary to have "token_type" field.
    """

    def restore(self, file_reference: str = None) -> Optional[Dict[str, Any]]:
        """
        :return: a dictionary with MCP tokens
        """
        tokens_str: str = os.getenv("AGENT_MCP_TOKENS")
        if tokens_str:
            try:
                tokens: Dict[str, Any] = json.loads(tokens_str)
                return tokens
            except json.JSONDecodeError as json_error:
                message: str = """
        There was an error parsing tokens from AGENT_MCP_TOKENS.
        See the accompanying JSONDecodeError exception (above) for clues as to what might be
        syntactically incorrect in that file.
        """
                raise ParseException(message) from json_error

        return None
