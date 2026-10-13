
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
    Canonical message-content fixtures for the content-block tests, shaped
    exactly like what the pinned langchain provider packages produce (or what
    clients send). Shared by the tests of every stage that handles message
    content, so each stage is exercised against the same shapes.
    """

    @staticmethod
    def anthropic_thinking_first() -> AIMessage:
        """
        :return: An AIMessage shaped like a ChatAnthropic response with
                 extended thinking enabled: the thinking block comes FIRST,
                 before the text block that holds the answer.
        """
        message = AIMessage(
            content=[
                {"type": "thinking", "thinking": "Let me reason this through.", "signature": "sig-abc"},
                {"type": "text", "text": "the answer"},
            ],
            response_metadata={"model_provider": "anthropic", "model_name": "claude-sonnet-4-5"},
        )
        return message

    @staticmethod
    def anthropic_tool_use() -> AIMessage:
        """
        :return: An AIMessage shaped like a ChatAnthropic tool-calling turn
                 WITHOUT reasoning enabled - list content of text + tool_use.
                 Anthropic tool-calling deployments produce this shape, so
                 its wire shape must stay the same.
        """
        message = AIMessage(
            content=[
                {"type": "text", "text": "Let me look that up."},
                {"type": "tool_use", "id": "toolu_1", "name": "lookup", "input": {"query": "q"}},
            ],
            tool_calls=[{"name": "lookup", "args": {"query": "q"}, "id": "toolu_1", "type": "tool_call"}],
            response_metadata={"model_provider": "anthropic", "model_name": "claude-sonnet-4-5"},
        )
        return message

    @staticmethod
    def openai_responses_reasoning() -> AIMessage:
        """
        :return: An AIMessage shaped like a ChatOpenAI (Responses API) reply
                 with reasoning summaries enabled.
        """
        message = AIMessage(
            content=[
                {"type": "reasoning", "id": "rs_1", "summary": [{"type": "summary_text", "text": "thought one"}]},
                {"type": "text", "text": "the answer", "id": "msg_1"},
            ],
            response_metadata={"model_provider": "openai", "model_name": "gpt-5"},
        )
        return message

    @staticmethod
    def v1_reasoning_blocks() -> AIMessage:
        """
        :return: An AIMessage whose content is already standard v1 blocks,
                 as produced by a chat model constructed with output_version="v1".
        """
        message = AIMessage(
            content=[
                {"type": "reasoning", "reasoning": "deep thought", "extras": {"signature": "sig-v1"}},
                {"type": "text", "text": "the answer"},
            ],
            response_metadata={"model_provider": "anthropic", "output_version": "v1"},
        )
        return message

    @staticmethod
    def multi_text_blocks() -> AIMessage:
        """
        :return: An AIMessage whose text is split across two text blocks
                 with a thinking block in between. Its full text is
                 "part one, part two"; the first text block alone holds
                 only "part one, ".
        """
        message = AIMessage(content=[
            {"type": "text", "text": "part one, "},
            {"type": "thinking", "thinking": "hmm"},
            {"type": "text", "text": "part two"},
        ])
        return message

    @staticmethod
    def list_of_str() -> AIMessage:
        """
        :return: An AIMessage with list-of-strings content (legal per the
                 pydantic annotation): two plain strings, no blocks, whose
                 full text is "part one, part two".
        """
        return AIMessage(content=["part one, ", "part two"])

    @staticmethod
    def mcp_tool_content() -> List[Dict[str, Any]]:
        """
        :return: Raw ToolMessage content shaped like what a block-returning
                 tool produces for a multi-part result: a list of content
                 blocks including binary data. Newer langchain-mcp-adapters
                 releases emit this shape; under the repo's pin (see
                 requirements.txt) MCP images go in the ToolMessage artifact
                 instead, so only toolbox tools reach it.
        """
        content: List[Dict[str, Any]] = [
            {"type": "text", "text": "Here is the chart."},
            {"type": "image", "base64": "aW1hZ2UtYnl0ZXM=", "mime_type": "image/png"},
        ]
        return content

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
        :return: An AIMessage with empty-list content, which omits the
                 "text" key on the wire.
        """
        return AIMessage(content=[])

    @staticmethod
    def multimodal_human() -> HumanMessage:
        """
        :return: A HumanMessage with standard v1 text + base64 image blocks,
                 as a multimodal client sends.
        """
        message = HumanMessage(content=[
            {"type": "text", "text": "Describe this image."},
            {"type": "image", "base64": "aW1hZ2UtYnl0ZXM=", "mime_type": "image/png"},
        ])
        return message
