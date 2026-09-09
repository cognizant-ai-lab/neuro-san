
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
# pylint: disable=protected-access
from typing import Any
from typing import Dict
from typing import List

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from langchain_core.messages.ai import AIMessage

from neuro_san.middleware.network_copy_middleware import NetworkCopyMiddleware


class TestNetworkCopyMiddleware:
    """
    Tests for how NetworkCopyMiddleware reads the model's response.

    The middleware runs inside langchain's agent loop and reads the
    provider-native AIMessage from the agent state. That message's content
    is a list of blocks rather than a str whenever the model emitted thinking
    or tool_use blocks, or was routed through the OpenAI Responses API.
    json.loads() raises TypeError on a list, which the middleware did not
    catch, so such requests ended with "Agent stopped due to exception".
    These tests lock the text projection that fixes it and confirm that
    plain-string responses behave exactly as before.
    """

    RESTORE_PATH: str = "neuro_san.middleware.network_copy_middleware.NetworkCopyMiddleware._restore_network"
    ASK_FOR_NAME: str = "Please provide the name of the network to copy."

    @staticmethod
    def make_middleware() -> NetworkCopyMiddleware:
        """
        Build a middleware whose reservationist is never reached by these tests.

        :return: A NetworkCopyMiddleware with a stub reservationist and empty sly_data
        """
        return NetworkCopyMiddleware(reservationist=MagicMock(), sly_data={})

    @staticmethod
    def make_state(content: Any) -> Dict[str, Any]:
        """
        Build a minimal agent state whose last message carries the given content.

        :param content: The content of the AIMessage that ends the agent state
        :return: An agent state dictionary shaped like langchain's AgentState
        """
        return {"messages": [AIMessage(content=content)]}

    @pytest.mark.asyncio
    async def test_str_json_content_parses_agent_name(self) -> None:
        """
        Plain-string JSON content, which every Chat Completions model produces,
        parses to the agent name and is looked up in the registry as before.
        """
        middleware: NetworkCopyMiddleware = self.make_middleware()
        state: Dict[str, Any] = self.make_state('{"agent_name": "hello_world"}')
        with patch(self.RESTORE_PATH, return_value=None) as restore:
            response: Dict[str, Any] = await middleware.aafter_agent(state, None)

        restore.assert_called_once_with("hello_world")
        assert "Cannot find agent hello_world" in response["messages"][0].content

    @pytest.mark.asyncio
    async def test_block_content_parses_agent_name(self) -> None:
        """
        The regression: Anthropic-style thinking-first block content whose text
        block holds the JSON. The old code handed the list to json.loads() and
        raised TypeError; now the text is projected first and the name parses.
        """
        blocks: List[Dict[str, Any]] = [
            {"type": "thinking", "thinking": "Which network was asked for?", "signature": "sig-abc"},
            {"type": "text", "text": '{"agent_name": "hello_world"}'},
        ]
        middleware: NetworkCopyMiddleware = self.make_middleware()
        with patch(self.RESTORE_PATH, return_value=None) as restore:
            response: Dict[str, Any] = await middleware.aafter_agent(self.make_state(blocks), None)

        restore.assert_called_once_with("hello_world")
        assert "Cannot find agent hello_world" in response["messages"][0].content

    @pytest.mark.asyncio
    async def test_responses_api_content_parses_agent_name(self) -> None:
        """
        The OpenAI Responses API shape (reasoning item first, then the text
        block) is the other live trigger of the old TypeError; it parses too.
        """
        blocks: List[Dict[str, Any]] = [
            {"type": "reasoning", "id": "rs_1", "summary": [{"type": "summary_text", "text": "thought"}]},
            {"type": "text", "text": '{"agent_name": "hello_world"}', "id": "msg_1"},
        ]
        middleware: NetworkCopyMiddleware = self.make_middleware()
        with patch(self.RESTORE_PATH, return_value=None) as restore:
            response: Dict[str, Any] = await middleware.aafter_agent(self.make_state(blocks), None)

        restore.assert_called_once_with("hello_world")
        assert "Cannot find agent hello_world" in response["messages"][0].content

    @pytest.mark.asyncio
    async def test_list_of_str_content_parses_agent_name(self) -> None:
        """
        List-of-str content is legal per the BaseMessage annotation and also
        raised TypeError in the old code; its pieces concatenate to the JSON.
        """
        parts: List[str] = ['{"agent_name": ', '"hello_world"}']
        middleware: NetworkCopyMiddleware = self.make_middleware()
        with patch(self.RESTORE_PATH, return_value=None) as restore:
            response: Dict[str, Any] = await middleware.aafter_agent(self.make_state(parts), None)

        restore.assert_called_once_with("hello_world")
        assert "Cannot find agent hello_world" in response["messages"][0].content

    @pytest.mark.asyncio
    async def test_block_content_without_text_asks_for_name(self) -> None:
        """
        Block content with no text block (a tool_use-only turn) projects to "",
        which is not JSON, so the middleware asks for the name instead of raising.
        """
        blocks: List[Dict[str, Any]] = [
            {"type": "tool_use", "id": "toolu_1", "name": "lookup", "input": {"query": "q"}},
        ]
        middleware: NetworkCopyMiddleware = self.make_middleware()
        with patch(self.RESTORE_PATH) as restore:
            response: Dict[str, Any] = await middleware.aafter_agent(self.make_state(blocks), None)

        restore.assert_not_called()
        assert response["messages"][0].content == self.ASK_FOR_NAME

    @pytest.mark.asyncio
    async def test_malformed_json_asks_for_name(self) -> None:
        """
        Non-JSON string content keeps producing the "please provide" prompt.
        """
        middleware: NetworkCopyMiddleware = self.make_middleware()
        with patch(self.RESTORE_PATH) as restore:
            response: Dict[str, Any] = await middleware.aafter_agent(self.make_state("not json"), None)

        restore.assert_not_called()
        assert response["messages"][0].content == self.ASK_FOR_NAME

    @pytest.mark.asyncio
    async def test_non_object_json_asks_for_name(self) -> None:
        """
        Valid JSON that is not an object (here a JSON array) has no agent_name
        key; the middleware asks for the name instead of raising AttributeError.
        """
        middleware: NetworkCopyMiddleware = self.make_middleware()
        with patch(self.RESTORE_PATH) as restore:
            response: Dict[str, Any] = await middleware.aafter_agent(self.make_state('["hello_world"]'), None)

        restore.assert_not_called()
        assert response["messages"][0].content == self.ASK_FOR_NAME

    def test_parse_agent_name_rejects_non_object_json(self) -> None:
        """
        Bare JSON strings and numbers decode fine but are not objects, so they
        yield None rather than an exception.
        """
        middleware: NetworkCopyMiddleware = self.make_middleware()
        assert middleware._parse_agent_name('"hello_world"') is None
        assert middleware._parse_agent_name("42") is None

    def test_parse_agent_name_tolerates_non_string(self) -> None:
        """
        _parse_agent_name catches TypeError alongside JSONDecodeError. The
        aafter_agent path always projects to str first, so this guards a
        hypothetical future caller that bypasses the projection: it gets None
        (and the "please provide" prompt) instead of an exception.
        """
        middleware: NetworkCopyMiddleware = self.make_middleware()
        assert middleware._parse_agent_name(["not", "a", "string"]) is None

    def test_parse_agent_name_strips_hocon_suffix(self) -> None:
        """
        An agent name given with its .hocon suffix is normalized to the bare name.
        """
        middleware: NetworkCopyMiddleware = self.make_middleware()
        assert middleware._parse_agent_name('{"agent_name": "hello_world.hocon"}') == "hello_world"
