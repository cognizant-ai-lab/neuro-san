
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

from langchain_core.messages.ai import AIMessage
from langchain_core.messages.human import HumanMessage


class ContentFixtures:
    """
    Canonical message-content fixtures for the content-block work, shaped
    exactly like what the pinned langchain provider packages produce (or what
    clients send). Shared by the ContentUtils unit tests and by the
    golden-parity suites of the follow-up PRs, so every stage of the pipeline
    is exercised against the same shapes.
    """

    @staticmethod
    def anthropic_thinking_first() -> AIMessage:
        """
        :return: An AIMessage shaped like a ChatAnthropic response with
                 extended thinking enabled: the thinking block comes FIRST,
                 which today's first-block flatten reduces to "".
        """
        return AIMessage(
            content=[
                {"type": "thinking", "thinking": "Let me reason this through.", "signature": "sig-abc"},
                {"type": "text", "text": "the answer"},
            ],
            response_metadata={"model_provider": "anthropic", "model_name": "claude-sonnet-4-5"},
        )

    @staticmethod
    def anthropic_tool_use() -> AIMessage:
        """
        :return: An AIMessage shaped like a ChatAnthropic tool-calling turn
                 WITHOUT reasoning enabled - list content of text + tool_use.
                 Every existing Anthropic tool-calling deployment produces
                 these today, so their wire shape must not change.
        """
        return AIMessage(
            content=[
                {"type": "text", "text": "Let me look that up."},
                {"type": "tool_use", "id": "toolu_1", "name": "lookup", "input": {"query": "q"}},
            ],
            tool_calls=[{"name": "lookup", "args": {"query": "q"}, "id": "toolu_1", "type": "tool_call"}],
            response_metadata={"model_provider": "anthropic", "model_name": "claude-sonnet-4-5"},
        )

    @staticmethod
    def openai_responses_reasoning() -> AIMessage:
        """
        :return: An AIMessage shaped like a ChatOpenAI (Responses API) reply
                 with reasoning summaries enabled.
        """
        return AIMessage(
            content=[
                {"type": "reasoning", "id": "rs_1",
                 "summary": [{"type": "summary_text", "text": "thought one"}]},
                {"type": "text", "text": "the answer", "id": "msg_1"},
            ],
            response_metadata={"model_provider": "openai", "model_name": "gpt-5"},
        )

    @staticmethod
    def v1_reasoning_blocks() -> AIMessage:
        """
        :return: An AIMessage whose content is already standard v1 blocks,
                 as produced by a chat model constructed with output_version="v1".
        """
        return AIMessage(
            content=[
                {"type": "reasoning", "reasoning": "deep thought", "extras": {"signature": "sig-v1"}},
                {"type": "text", "text": "the answer"},
            ],
            response_metadata={"model_provider": "anthropic", "output_version": "v1"},
        )

    @staticmethod
    def list_of_str() -> AIMessage:
        """
        :return: An AIMessage with list-of-strings content - legal per the
                 pydantic annotation, and a crash (AttributeError) in today's
                 first-block flatten.
        """
        return AIMessage(content=["part one, ", "part two"])

    @staticmethod
    def mcp_tool_content() -> List[Dict[str, Any]]:
        """
        :return: Raw ToolMessage content shaped like what
                 langchain-mcp-adapters>=0.2.0 produces for a multi-part MCP
                 tool result: a list of content blocks including binary data.
        """
        return [
            {"type": "text", "text": "Here is the chart."},
            {"type": "image", "base64": "aW1hZ2UtYnl0ZXM=", "mime_type": "image/png"},
        ]

    @staticmethod
    def whitespace_text() -> AIMessage:
        """
        :return: An AIMessage with plain-string content that has leading and
                 trailing whitespace - locks down where stripping does and
                 does not happen.
        """
        return AIMessage(content="  the answer  ")

    @staticmethod
    def empty_list_content() -> AIMessage:
        """
        :return: An AIMessage with empty-list content, which today omits the
                 "text" key on the wire (and must continue to).
        """
        return AIMessage(content=[])

    @staticmethod
    def multimodal_human() -> HumanMessage:
        """
        :return: A HumanMessage with standard v1 text + base64 image blocks,
                 as a multimodal client would send (Phase 3).
        """
        return HumanMessage(content=[
            {"type": "text", "text": "Describe this image."},
            {"type": "image", "base64": "aW1hZ2UtYnl0ZXM=", "mime_type": "image/png"},
        ])
