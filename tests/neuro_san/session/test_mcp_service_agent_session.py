
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
from typing import List

import json

from unittest import TestCase
from unittest.mock import MagicMock
from unittest.mock import patch

from neuro_san.session.mcp_service_agent_session import McpServiceAgentSession


class TestMcpServiceAgentSession(TestCase):
    """
    Unit tests for McpServiceAgentSession's tool naming: users pass the network name
    ("deep/math_guy") but the server advertises and expects the provider-safe
    tool name ("deep__math_guy"), so the session must translate. It also remembers
    which spelling the server advertised so tools/call works against servers from
    before the rename.
    """

    POST_TARGET: str = "neuro_san.session.mcp_service_agent_session.post"
    NETWORK_NAME: str = "deep/math_guy"
    TOOL_NAME: str = "deep__math_guy"
    DESCRIPTION: str = "Does math"

    @staticmethod
    def fake_post(path: str, **kwargs: Any) -> MagicMock:
        """
        Stands in for requests.post(), answering the MCP handshake and tools/list
        the way a neuro-san server that advertises provider-safe names would.

        :param path: The URL posted to; unused
        :param kwargs: The keyword arguments requests.post() was given; "json" carries the JSON-RPC payload
        :return: A MagicMock response with .text set to the JSON-RPC reply
        """
        _ = path
        payload: Dict[str, Any] = kwargs.get("json") or {}
        method: str = payload.get("method")

        body: Dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "result": {}}
        if method == "initialize":
            body["result"] = {"protocolVersion": "2025-06-18"}
        elif method == "tools/list":
            body["result"] = {
                "tools": [
                    {
                        "name": TestMcpServiceAgentSession.TOOL_NAME,
                        "title": TestMcpServiceAgentSession.NETWORK_NAME,
                        "description": TestMcpServiceAgentSession.DESCRIPTION
                    }
                ]
            }

        response: MagicMock = MagicMock()
        response.raise_for_status.return_value = None
        response.text = json.dumps(body)
        # streaming_chat() uses the response as a context manager and iterates its lines.
        response.__enter__.return_value = response
        response.iter_lines.return_value = []
        return response

    @staticmethod
    def fake_legacy_post(path: str, **kwargs: Any) -> MagicMock:
        """
        Stands in for requests.post() against a server from before the rename,
        which advertises the raw network name as the tool name.

        :param path: The URL posted to; passed on to fake_post()
        :param kwargs: The keyword arguments requests.post() was given
        :return: A MagicMock response whose tools/list entry is named after the network
        """
        response: MagicMock = TestMcpServiceAgentSession.fake_post(path, **kwargs)
        payload: Dict[str, Any] = kwargs.get("json") or {}
        if payload.get("method") == "tools/list":
            body: Dict[str, Any] = json.loads(response.text)
            body["result"]["tools"][0]["name"] = TestMcpServiceAgentSession.NETWORK_NAME
            del body["result"]["tools"][0]["title"]
            response.text = json.dumps(body)
        return response

    @staticmethod
    def find_payload(mock_post: MagicMock, method: str) -> Dict[str, Any]:
        """
        Finds the first JSON-RPC payload posted with the given method.

        :param mock_post: The patched requests.post
        :param method: The JSON-RPC method to look for
        :return: The first posted JSON payload with that method, or None
        """
        for call in mock_post.call_args_list:
            payload: Dict[str, Any] = call.kwargs.get("json") or {}
            if payload.get("method") == method:
                return payload
        return None

    def test_constructor_derives_safe_tool_name(self) -> None:
        """
        The session keeps the network name the user gave and derives the tool name from it.
        """
        with patch(self.POST_TARGET, side_effect=self.fake_post):
            session = McpServiceAgentSession(agent_name=self.NETWORK_NAME)
        self.assertEqual(self.NETWORK_NAME, session.agent_name)
        self.assertEqual(self.TOOL_NAME, session.mcp_tool_name)

    def test_top_level_name_is_unchanged(self) -> None:
        """
        A top-level network has no "/" so both spellings coincide.
        """
        with patch(self.POST_TARGET, side_effect=self.fake_post):
            session = McpServiceAgentSession(agent_name="math_guy")
        self.assertEqual("math_guy", session.mcp_tool_name)

    def test_streaming_chat_calls_tool_by_safe_name(self) -> None:
        """
        Before function() has seen what the server advertises, the tools/call
        payload names the tool by the provider-safe spelling, not by the network
        name the user passed.
        """
        with patch(self.POST_TARGET, side_effect=self.fake_post) as mock_post:
            session = McpServiceAgentSession(agent_name=self.NETWORK_NAME)
            responses: List[Dict[str, Any]] = list(session.streaming_chat({"user_message": {"text": "2+2"}}))

        self.assertEqual([], responses)
        payload: Dict[str, Any] = self.find_payload(mock_post, "tools/call")
        self.assertIsNotNone(payload)
        self.assertEqual(self.TOOL_NAME, payload["params"]["name"])
        self.assertEqual({"user_message": {"text": "2+2"}}, payload["params"]["arguments"])

    def test_function_matches_safe_tool_name(self) -> None:
        """
        function() finds the tools/list entry advertised under the provider-safe name
        even though the session was created with the network name.
        """
        with patch(self.POST_TARGET, side_effect=self.fake_post):
            session = McpServiceAgentSession(agent_name=self.NETWORK_NAME)
            function_dict: Dict[str, Any] = session.function({})
        self.assertEqual({"function": {"description": self.DESCRIPTION}}, function_dict)

    def test_function_still_matches_network_name(self) -> None:
        """
        Against an older server that advertises the raw network name, function() still matches.
        """
        with patch(self.POST_TARGET, side_effect=self.fake_legacy_post):
            session = McpServiceAgentSession(agent_name=self.NETWORK_NAME)
            function_dict: Dict[str, Any] = session.function({})
        self.assertEqual({"function": {"description": self.DESCRIPTION}}, function_dict)

    def test_function_returns_none_when_neither_spelling_is_listed(self) -> None:
        """
        A session for a network the server does not list gets None from function().
        """
        with patch(self.POST_TARGET, side_effect=self.fake_post):
            session = McpServiceAgentSession(agent_name="other/network")
            function_dict: Dict[str, Any] = session.function({})
        self.assertIsNone(function_dict)

    def test_function_records_spelling_advertised_by_legacy_server(self) -> None:
        """
        Against an older server that lists the raw network name, function() records
        that spelling so the following tools/call uses a name the server can resolve.
        """
        with patch(self.POST_TARGET, side_effect=self.fake_legacy_post) as mock_post:
            session = McpServiceAgentSession(agent_name=self.NETWORK_NAME)
            session.function({})
            list(session.streaming_chat({"user_message": {"text": "2+2"}}))
        self.assertEqual(self.NETWORK_NAME, session.mcp_tool_name)
        payload: Dict[str, Any] = self.find_payload(mock_post, "tools/call")
        self.assertIsNotNone(payload)
        self.assertEqual(self.NETWORK_NAME, payload["params"]["name"])

    def test_function_keeps_safe_spelling_against_renaming_server(self) -> None:
        """
        Against a server that advertises the provider-safe name, function() leaves
        the tool name as that spelling and tools/call uses it.
        """
        with patch(self.POST_TARGET, side_effect=self.fake_post) as mock_post:
            session = McpServiceAgentSession(agent_name=self.NETWORK_NAME)
            session.function({})
            list(session.streaming_chat({"user_message": {"text": "2+2"}}))
        self.assertEqual(self.TOOL_NAME, session.mcp_tool_name)
        payload: Dict[str, Any] = self.find_payload(mock_post, "tools/call")
        self.assertIsNotNone(payload)
        self.assertEqual(self.TOOL_NAME, payload["params"]["name"])
