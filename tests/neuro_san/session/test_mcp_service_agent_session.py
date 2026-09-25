
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

from functools import partial
import json
import os

from unittest import TestCase
from unittest.mock import MagicMock
from unittest.mock import patch

from typing_extensions import override

from neuro_san.session.mcp_service_agent_session import McpServiceAgentSession
from neuro_san.session.session_util import SessionUtil


class TestMcpServiceAgentSession(TestCase):
    """
    Unit tests for McpServiceAgentSession's tool naming. Users pass the network name
    ("deep/math_guy"), but a server may advertise the network under another name,
    such as the provider-safe spelling ("deep__math_guy") or an alias ("calculator"),
    carrying the network name in the MCP "title" (see AgentNetwork.set_as_mcp_tool()).
    The session must find its tool in tools/list by that title, or by name when there
    is no title, then call it by the name the server advertised. Before it has looked,
    it calls by the network name, which every neuro-san server accepts.
    """

    POST_TARGET: str = "neuro_san.session.mcp_service_agent_session.post"
    NETWORK_NAME: str = "deep/math_guy"
    TOOL_NAME: str = "deep__math_guy"
    CUSTOM_NAME: str = "calculator"
    DESCRIPTION: str = "Does math"

    # What one tools/list entry looks like from each kind of server: the network
    # under its own name, under the provider-safe spelling, or under an alias.
    LEGACY_TOOL: Dict[str, Any] = {"name": NETWORK_NAME, "description": DESCRIPTION}
    RENAMED_TOOL: Dict[str, Any] = {"name": TOOL_NAME, "title": NETWORK_NAME, "description": DESCRIPTION}
    CUSTOM_TOOL: Dict[str, Any] = {"name": CUSTOM_NAME, "title": NETWORK_NAME, "description": DESCRIPTION}
    # An unrelated top-level network that happens to be literally named "deep__math_guy".
    LOOKALIKE_TOOL: Dict[str, Any] = {"name": TOOL_NAME, "description": "Some other network"}

    @override
    def setUp(self) -> None:
        """
        Pins the environment so that a MAX_AGENTS_FROM_EXTERNAL_SERVER exported in the
        developer's shell cannot truncate the tools/list these tests advertise.
        """
        # patch.dict snapshots os.environ on start() and restores the whole mapping on stop(),
        # so the variable can simply be removed here and any per-test value set later; both
        # are undone by the cleanup, which runs even if the test raises.
        env_patcher: Any = patch.dict(os.environ)
        env_patcher.start()
        self.addCleanup(env_patcher.stop)
        os.environ.pop(SessionUtil.MAX_AGENTS_ENV_VAR, None)

    @staticmethod
    def fake_post(tools: List[Dict[str, Any]], path: str, **kwargs: Any) -> MagicMock:
        """
        Stands in for requests.post(), answering the MCP handshake and a tools/list
        that advertises the given tools.

        :param tools: The tools/list entries the fake server advertises
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
            body["result"] = {"tools": tools}

        response: MagicMock = MagicMock()
        response.raise_for_status.return_value = None
        response.text = json.dumps(body)
        # streaming_chat() uses the response as a context manager and iterates its lines.
        response.__enter__.return_value = response
        response.iter_lines.return_value = []
        return response

    def patch_post(self, *tools: Dict[str, Any]) -> Any:
        """
        Patches requests.post() in the session module with a fake server.

        :param tools: The tools/list entries the fake server advertises
        :return: The patch context manager; entering it yields the mock post
        """
        return patch(self.POST_TARGET, side_effect=partial(self.fake_post, list(tools)))

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

    def test_constructor_has_not_learned_advertised_name(self) -> None:
        """
        The session keeps the network name and has not yet asked the server
        what it advertises.
        """
        with self.patch_post(self.RENAMED_TOOL):
            session = McpServiceAgentSession(agent_name=self.NETWORK_NAME)
        self.assertEqual(self.NETWORK_NAME, session.agent_name)
        self.assertIsNone(session.advertised_tool_name)

    def test_streaming_chat_before_function_uses_network_name(self) -> None:
        """
        A caller that never runs function() has not learned the advertised name,
        so tools/call uses the network name, which every neuro-san server accepts.
        """
        with self.patch_post(self.RENAMED_TOOL) as mock_post:
            session = McpServiceAgentSession(agent_name=self.NETWORK_NAME)
            responses: List[Dict[str, Any]] = list(session.streaming_chat({"user_message": {"text": "2+2"}}))

        self.assertEqual([], responses)
        payload: Dict[str, Any] = self.find_payload(mock_post, "tools/call")
        self.assertIsNotNone(payload)
        self.assertEqual(self.NETWORK_NAME, payload["params"]["name"])
        self.assertEqual({"user_message": {"text": "2+2"}}, payload["params"]["arguments"])

    def test_function_matches_network_name_on_legacy_server(self) -> None:
        """
        Against an older server that advertises the raw network name, function()
        finds the tool and tools/call keeps using that name.
        """
        with self.patch_post(self.LEGACY_TOOL) as mock_post:
            session = McpServiceAgentSession(agent_name=self.NETWORK_NAME)
            function_dict: Dict[str, Any] = session.function({})
            list(session.streaming_chat({"user_message": {"text": "2+2"}}))
        self.assertEqual({"function": {"description": self.DESCRIPTION}}, function_dict)
        self.assertEqual(self.NETWORK_NAME, session.advertised_tool_name)
        payload: Dict[str, Any] = self.find_payload(mock_post, "tools/call")
        self.assertEqual(self.NETWORK_NAME, payload["params"]["name"])

    def test_function_matches_title_of_renamed_tool(self) -> None:
        """
        Against a server that advertises the provider-safe name with the network
        name as title, function() finds the tool by the title and tools/call uses
        the advertised name.
        """
        with self.patch_post(self.RENAMED_TOOL) as mock_post:
            session = McpServiceAgentSession(agent_name=self.NETWORK_NAME)
            function_dict: Dict[str, Any] = session.function({})
            list(session.streaming_chat({"user_message": {"text": "2+2"}}))
        self.assertEqual({"function": {"description": self.DESCRIPTION}}, function_dict)
        self.assertEqual(self.TOOL_NAME, session.advertised_tool_name)
        payload: Dict[str, Any] = self.find_payload(mock_post, "tools/call")
        self.assertEqual(self.TOOL_NAME, payload["params"]["name"])

    def test_function_matches_title_when_server_uses_custom_name(self) -> None:
        """
        Against a server that advertises the network under an alias unrelated to
        its name, function() recognises the entry by its title and records the
        alias so the following tools/call uses it.
        """
        with self.patch_post(self.CUSTOM_TOOL) as mock_post:
            session = McpServiceAgentSession(agent_name=self.NETWORK_NAME)
            function_dict: Dict[str, Any] = session.function({})
            list(session.streaming_chat({"user_message": {"text": "2+2"}}))
        self.assertEqual({"function": {"description": self.DESCRIPTION}}, function_dict)
        self.assertEqual(self.CUSTOM_NAME, session.advertised_tool_name)
        payload: Dict[str, Any] = self.find_payload(mock_post, "tools/call")
        self.assertEqual(self.CUSTOM_NAME, payload["params"]["name"])

    def test_function_ignores_custom_name_titled_for_another_network(self) -> None:
        """
        A title naming some other network does not make an aliased tool match,
        and nothing is recorded as advertised.
        """
        with self.patch_post(self.CUSTOM_TOOL):
            session = McpServiceAgentSession(agent_name="deep/other_guy")
            function_dict: Dict[str, Any] = session.function({})
        self.assertIsNone(function_dict)
        self.assertIsNone(session.advertised_tool_name)

    def test_function_does_not_guess_from_provider_safe_spelling(self) -> None:
        """
        An untitled entry named "deep__math_guy" is a network of that very name,
        not a renamed "deep/math_guy". This is what a server lists after a name
        collision withdrew the nested network from MCP, so guessing would send
        the chat to the wrong network.
        """
        with self.patch_post(self.LOOKALIKE_TOOL):
            session = McpServiceAgentSession(agent_name=self.NETWORK_NAME)
            function_dict: Dict[str, Any] = session.function({})
        self.assertIsNone(function_dict)
        self.assertIsNone(session.advertised_tool_name)

    def test_function_picks_titled_entry_over_lookalike_name(self) -> None:
        """
        When an unrelated network is literally named "deep__math_guy" and the
        wanted network is advertised under a custom name with a matching title,
        the titled entry is chosen even though the lookalike is listed first.
        """
        with self.patch_post(self.LOOKALIKE_TOOL, self.CUSTOM_TOOL) as mock_post:
            session = McpServiceAgentSession(agent_name=self.NETWORK_NAME)
            function_dict: Dict[str, Any] = session.function({})
            list(session.streaming_chat({"user_message": {"text": "2+2"}}))
        self.assertEqual({"function": {"description": self.DESCRIPTION}}, function_dict)
        self.assertEqual(self.CUSTOM_NAME, session.advertised_tool_name)
        payload: Dict[str, Any] = self.find_payload(mock_post, "tools/call")
        self.assertEqual(self.CUSTOM_NAME, payload["params"]["name"])

    def test_title_overrides_a_matching_name(self) -> None:
        """
        An entry named "math_guy" but titled "x/y" is x/y's tool advertised under
        the custom name "math_guy": a session for "math_guy" must not take it,
        while a session for "x/y" must.
        """
        borrowed_name_tool: Dict[str, Any] = {"name": "math_guy", "title": "x/y", "description": "x over y"}
        with self.patch_post(borrowed_name_tool):
            math_session = McpServiceAgentSession(agent_name="math_guy")
            math_function: Dict[str, Any] = math_session.function({})
            xy_session = McpServiceAgentSession(agent_name="x/y")
            xy_function: Dict[str, Any] = xy_session.function({})
        self.assertIsNone(math_function)
        self.assertEqual({"function": {"description": "x over y"}}, xy_function)
        self.assertEqual("math_guy", xy_session.advertised_tool_name)

    def test_function_returns_none_when_network_is_not_listed(self) -> None:
        """
        A session for a network the server does not list gets None from function().
        """
        with self.patch_post(self.RENAMED_TOOL):
            session = McpServiceAgentSession(agent_name="other/network")
            function_dict: Dict[str, Any] = session.function({})
        self.assertIsNone(function_dict)

    def test_function_records_name_of_tool_without_description(self) -> None:
        """
        A matched entry with no description gives function() nothing to return,
        but the advertised name is still remembered so tools/call can use it.
        """
        undescribed_tool: Dict[str, Any] = {"name": self.TOOL_NAME, "title": self.NETWORK_NAME}
        with self.patch_post(undescribed_tool) as mock_post:
            session = McpServiceAgentSession(agent_name=self.NETWORK_NAME)
            function_dict: Dict[str, Any] = session.function({})
            list(session.streaming_chat({"user_message": {"text": "2+2"}}))
        self.assertIsNone(function_dict)
        self.assertEqual(self.TOOL_NAME, session.advertised_tool_name)
        payload: Dict[str, Any] = self.find_payload(mock_post, "tools/call")
        self.assertEqual(self.TOOL_NAME, payload["params"]["name"])

    def test_function_forgets_advertised_name_when_network_disappears(self) -> None:
        """
        If a later tools/list no longer contains the network, function() drops the
        name it learned earlier and tools/call goes back to the network name.
        """
        # The fake server reads this list on every call, so emptying it between
        # calls simulates the network being withdrawn.
        tools: List[Dict[str, Any]] = [self.RENAMED_TOOL]
        with patch(self.POST_TARGET, side_effect=partial(self.fake_post, tools)) as mock_post:
            session = McpServiceAgentSession(agent_name=self.NETWORK_NAME)
            first: Dict[str, Any] = session.function({})
            tools.clear()
            second: Dict[str, Any] = session.function({})
            list(session.streaming_chat({"user_message": {"text": "2+2"}}))
        self.assertEqual({"function": {"description": self.DESCRIPTION}}, first)
        self.assertIsNone(second)
        self.assertIsNone(session.advertised_tool_name)
        payload: Dict[str, Any] = self.find_payload(mock_post, "tools/call")
        self.assertEqual(self.NETWORK_NAME, payload["params"]["name"])

    def test_find_tool_for_network_skips_entry_without_name(self) -> None:
        """
        A tools/list entry with no "name" cannot be called, so it never matches,
        even when its title is the network name.
        """
        with self.patch_post():
            session = McpServiceAgentSession(agent_name=self.NETWORK_NAME)
        self.assertIsNone(session.find_tool_for_network([{"title": self.NETWORK_NAME}]))

    def test_find_tool_for_network_treats_empty_title_as_absent(self) -> None:
        """
        An empty title says nothing about the network, so the name decides.
        """
        blank_title_tool: Dict[str, Any] = {"name": self.NETWORK_NAME, "title": "", "description": self.DESCRIPTION}
        with self.patch_post():
            session = McpServiceAgentSession(agent_name=self.NETWORK_NAME)
        self.assertIs(blank_title_tool, session.find_tool_for_network([blank_title_tool]))

    def test_function_applies_max_agents_limit_before_searching(self) -> None:
        """
        MAX_AGENTS_FROM_EXTERNAL_SERVER bounds the tools/list entries considered, and does so
        before the search: a network listed beyond the limit is not found, and the truncation
        is logged so the "not implemented" the CLI then reports can be traced to the setting.
        """
        os.environ[SessionUtil.MAX_AGENTS_ENV_VAR] = "1"
        with self.patch_post(self.LOOKALIKE_TOOL, self.CUSTOM_TOOL):
            session = McpServiceAgentSession(agent_name=self.NETWORK_NAME)
            with self.assertLogs(SessionUtil.__name__, level="WARNING"):
                function_dict: Dict[str, Any] = session.function({})
        self.assertIsNone(function_dict)
        self.assertIsNone(session.advertised_tool_name)

    def test_session_without_network_finds_nothing(self) -> None:
        """
        A session created without an agent name has no tool to look for, so no
        entry matches, not even one that also lacks name or title.
        """
        with self.patch_post(self.LEGACY_TOOL):
            session = McpServiceAgentSession(agent_name=None)
            function_dict: Dict[str, Any] = session.function({})
        self.assertIsNone(function_dict)
        self.assertIsNone(session.find_tool_for_network([{"name": "anything"}, {"description": "nameless"}]))
