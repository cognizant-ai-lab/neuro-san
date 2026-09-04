
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

import json
from unittest import TestCase
from unittest.mock import MagicMock
from unittest.mock import patch

from neuro_san.session.mcp_service_agent_session import MCP_VERSION
from neuro_san.session.mcp_service_agent_session import McpServiceAgentSession


class TestMcpServiceAgentSession(TestCase):
    """
    Unit tests for McpServiceAgentSession.
    """

    @staticmethod
    def create_response(response_dict: Dict[str, Any]) -> MagicMock:
        """
        Creates a successful HTTP response containing response_dict.
        """
        response: MagicMock = MagicMock()
        response.text = json.dumps(response_dict)
        return response

    def call_function(self, tools: Any) -> Dict[str, Any]:
        """
        Calls function() with a tools/list response containing tools.
        """
        initialize_response: MagicMock = self.create_response({
            "result": {"protocolVersion": MCP_VERSION}
        })
        initialized_response: MagicMock = self.create_response({})
        tools_response: MagicMock = self.create_response({"result": {"tools": tools}})

        with patch("neuro_san.session.mcp_service_agent_session.requests.post",
                   side_effect=[initialize_response, initialized_response, tools_response]):
            session = McpServiceAgentSession(agent_name="hello_world")
            return session.function({})

    def test_function_accepts_valid_tools(self):
        """
        Tests that a valid tools/list response returns the matching tool description.
        """
        result: Dict[str, Any] = self.call_function([
            {"name": "hello_world", "description": "Says hello"}
        ])

        self.assertEqual({"function": {"description": "Says hello"}}, result)

    def test_function_rejects_invalid_tools(self):
        """
        Tests that tools/list response data is validated before iteration.
        """
        invalid_tools = (
            "hello_world",
            ["hello_world"],
            [{}] * (McpServiceAgentSession.MAX_TOOLS + 1),
        )

        for tools in invalid_tools:
            with self.subTest(tools_type=type(tools), tools_length=len(tools)):
                with self.assertRaisesRegex(ValueError, "Invalid MCP tools/list response"):
                    self.call_function(tools)
