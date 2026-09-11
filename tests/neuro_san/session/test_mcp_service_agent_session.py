
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

    VALID_INITIALIZE_RESULT: Dict[str, Any] = {
        "protocolVersion": MCP_VERSION,
        "capabilities": {},
        "serverInfo": {"name": "test_server", "version": "1.0.0"},
    }

    @staticmethod
    def create_response(response_dict: Any) -> MagicMock:
        """
        Creates a successful HTTP response containing response_dict.
        """
        response: MagicMock = MagicMock()
        response.text = json.dumps(response_dict)
        return response

    def call_function_with_response(self, response_dict: Any) -> Dict[str, Any]:
        """
        Calls function() with the given tools/list response.
        """
        initialize_response: MagicMock = self.create_response({
            "result": self.VALID_INITIALIZE_RESULT
        })
        initialized_response: MagicMock = self.create_response({})
        tools_response: MagicMock = self.create_response(response_dict)

        with patch("neuro_san.session.mcp_service_agent_session.requests.post",
                   side_effect=[initialize_response, initialized_response, tools_response]):
            session = McpServiceAgentSession(agent_name="hello_world")
            return session.function({})

    def call_function(self, tools: Any) -> Dict[str, Any]:
        """
        Calls function() with a tools/list response containing tools.
        """
        return self.call_function_with_response({"result": {"tools": tools}})

    @staticmethod
    def create_tool(name: str, description: str = None) -> Dict[str, Any]:
        """
        Creates a tool that conforms to the MCP Tool schema.
        """
        tool: Dict[str, Any] = {
            "name": name,
            "inputSchema": {"type": "object"},
        }
        if description is not None:
            tool["description"] = description
        return tool

    def create_session_with_initialize_response(self, response_dict: Any) -> McpServiceAgentSession:
        """
        Creates an MCP session with the given initialize response.
        """
        initialize_response: MagicMock = self.create_response(response_dict)
        with patch("neuro_san.session.mcp_service_agent_session.requests.post",
                   return_value=initialize_response):
            return McpServiceAgentSession(agent_name="hello_world")

    def test_function_accepts_valid_tools(self):
        """
        Tests that a valid tools/list response returns the matching tool description.
        """
        result: Dict[str, Any] = self.call_function([
            self.create_tool("hello_world", "Says hello")
        ])

        self.assertEqual({"function": {"description": "Says hello"}}, result)

    def test_function_rejects_invalid_tools(self):
        """
        Tests that tools/list response data is validated before iteration.
        """
        invalid_responses = (
            ([], "Invalid MCP tools/list response: response must be an object"),
            ({"result": None}, "Invalid MCP tools/list response: 'result' must be an object"),
            ({"result": []}, "Invalid MCP tools/list response: 'result' must be an object"),
            ({"result": {}},
             "Invalid MCP tools/list response: 'result' does not match ListToolsResult"),
            ({"result": {"tools": None}},
             "Invalid MCP tools/list response: 'result' does not match ListToolsResult"),
            ({"result": {"tools": "hello_world"}},
             "Invalid MCP tools/list response: 'result' does not match ListToolsResult"),
            ({"result": {"tools": [{"name": "hello_world"}]}},
             "Invalid MCP tools/list response: 'result' does not match ListToolsResult"),
        )

        for response_dict, expected_message in invalid_responses:
            with self.subTest(response_dict=response_dict):
                with self.assertRaises(ValueError) as context:
                    self.call_function_with_response(response_dict)
                self.assertEqual(expected_message, str(context.exception))

    def test_function_surfaces_json_rpc_error(self):
        """
        Tests that a successful HTTP response containing a JSON-RPC error is surfaced.
        """
        response_dict = {
            "error": {"code": -32602, "message": "Invalid params"}
        }

        with self.assertRaises(ValueError) as context:
            self.call_function_with_response(response_dict)

        self.assertEqual("MCP tools/list error -32602: Invalid params", str(context.exception))

    def test_function_rejects_invalid_tool(self):
        """
        Tests that a malformed tool causes the ListToolsResult schema validation to fail.
        """
        with self.assertRaises(ValueError) as context:
            self.call_function([None, self.create_tool("hello_world", "Says hello")])

        self.assertEqual(
            "Invalid MCP tools/list response: 'result' does not match ListToolsResult",
            str(context.exception),
        )

    def test_initialize_rejects_invalid_response(self):
        """
        Tests that the initialize response and its result object are validated.
        """
        invalid_responses = (
            ([], "Invalid MCP initialize response: response must be an object"),
            ({"result": None}, "Invalid MCP initialize response: 'result' must be an object"),
            ({"result": []}, "Invalid MCP initialize response: 'result' must be an object"),
            ({"result": {"protocolVersion": MCP_VERSION}},
             "Invalid MCP initialize response: 'result' does not match InitializeResult"),
        )

        for response_dict, expected_message in invalid_responses:
            with self.subTest(response_dict=response_dict):
                with self.assertRaises(ValueError) as context:
                    self.create_session_with_initialize_response(response_dict)
                self.assertEqual(expected_message, str(context.exception))

    def test_initialize_surfaces_json_rpc_error(self):
        """
        Tests that a JSON-RPC error in the initialize response is surfaced.
        """
        response_dict = {
            "error": {"code": -32602, "message": "Invalid params"}
        }

        with self.assertRaises(ValueError) as context:
            self.create_session_with_initialize_response(response_dict)

        self.assertEqual("MCP initialize error -32602: Invalid params", str(context.exception))

    def test_function_accepts_more_than_one_thousand_tools(self):
        """
        Tests that the client does not impose a limit absent from the MCP specification.
        """
        tools = [self.create_tool(f"tool_{index}") for index in range(1001)]
        tools.append(self.create_tool("hello_world", "Says hello"))

        result: Dict[str, Any] = self.call_function(tools)

        self.assertEqual({"function": {"description": "Says hello"}}, result)
