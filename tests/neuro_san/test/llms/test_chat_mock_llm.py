
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

from unittest import TestCase

from langchain_core.messages.ai import AIMessage
from langchain_core.messages.human import HumanMessage

from neuro_san.message.utils.content_utils import ContentUtils
from neuro_san.test.llms.chat_mock_llm import ChatMockLlm

from tests.neuro_san.message.content_fixtures import ContentFixtures


class TestChatMockLlm(TestCase):
    """
    Tests for the block-aware behaviors of the mock chat model:
    the plain-string echo is unchanged, list-of-blocks input does not crash
    token counting or streaming, and the ANTHROPIC_THINKING_MARKER,
    OPENAI_REASONING_MARKER and GEMINI_THINKING_MARKER hooks produce
    Anthropic-style thinking-first, OpenAI Responses-style reasoning-first and
    Gemini-style thinking-then-signed-text block content for keyless testing.
    """

    @staticmethod
    def make_llm() -> ChatMockLlm:
        """
        :return: A ChatMockLlm for testing
        """
        return ChatMockLlm(model="mock-llm")

    def test_plain_string_echo_unchanged(self):
        """
        The mock echoes plain-string input with symmetric token accounting.
        """
        llm = self.make_llm()
        result = llm.invoke("hello there")
        assert result.content == "hello there"
        usage = result.usage_metadata
        assert usage["input_tokens"] == usage["output_tokens"]
        assert usage["total_tokens"] == 2 * usage["input_tokens"]

    def test_block_content_input_does_not_crash(self):
        """
        Multimodal (list-of-blocks) input flows through _generate and _stream:
        tokens are counted on the flattened text and the echo/stream carry on.
        """
        llm = self.make_llm()
        message = ContentFixtures.multimodal_human()

        result = llm.invoke([message])
        assert result.content == message.content
        assert result.usage_metadata["input_tokens"] > 0

        streamed = list(llm.stream([message]))
        streamed_text = "".join(ContentUtils.flatten_to_text(chunk.content) for chunk in streamed)
        assert streamed_text == "Describe this image."

    def test_anthropic_thinking_marker_emits_thinking_first_blocks(self):
        """
        The marker makes _generate respond like ChatAnthropic with extended
        thinking: a thinking block first, then the text answer, with
        model_provider stamped so standardization translates it.
        """
        llm = self.make_llm()
        result = llm.invoke([HumanMessage(content="emit anthropic thinking: the answer")])

        assert isinstance(result.content, list)
        assert result.content[0]["type"] == "thinking"
        assert result.response_metadata["model_provider"] == "anthropic"

        blocks = ContentUtils.standard_blocks(result)
        assert [block["type"] for block in blocks] == ["reasoning", "text"]
        assert blocks[1]["text"] == "the answer"
        assert ContentUtils.flatten_to_text(result) == "the answer"

    def test_openai_reasoning_marker_emits_reasoning_item_first(self) -> None:
        """
        The OpenAI marker yields the Responses API shape: a raw reasoning item
        with id, summary parts, empty content and encrypted_content ahead of the
        text item, stamped as provider openai. Normalization explodes the two
        summary parts into two reasoning blocks and keeps the answer text intact.
        """
        llm: ChatMockLlm = self.make_llm()
        result: AIMessage = llm.invoke([HumanMessage(content="emit openai reasoning: the answer")])

        self.assertIsInstance(result.content, list)
        self.assertEqual(result.content[0]["type"], "reasoning")
        self.assertIn("encrypted_content", result.content[0])
        self.assertEqual(result.response_metadata["model_provider"], "openai")

        blocks: List[Dict[str, Any]] = ContentUtils.normalize_message(result).content
        block_types: List[str] = []
        for block in blocks:
            block_types.append(block["type"])
        self.assertEqual(block_types, ["reasoning", "reasoning", "text"])
        self.assertIn("encrypted_content", blocks[0])
        self.assertEqual(blocks[2]["text"], "the answer")
        self.assertEqual(ContentUtils.flatten_to_text(result), "the answer")

    def test_gemini_thinking_marker_emits_thinking_then_signed_text(self) -> None:
        """
        The Gemini marker yields the langchain-google-genai shape for Gemini 3
        with include_thoughts on: a thinking block holding only the thought
        text, then the text block carrying the thought signature in its extras,
        stamped as provider google_genai. Normalization turns the thinking block
        into a reasoning block and keeps the signed text block intact.
        """
        llm: ChatMockLlm = self.make_llm()
        result: AIMessage = llm.invoke([HumanMessage(content="emit gemini thinking: the answer")])

        self.assertIsInstance(result.content, list)
        self.assertEqual(result.content[0]["type"], "thinking")
        # Gemini 3 signs the text part, not the thought part.
        self.assertNotIn("signature", result.content[0])
        self.assertEqual(result.content[1]["extras"], {"signature": "mock-thought-signature"})
        self.assertEqual(result.response_metadata["model_provider"], "google_genai")

        blocks: List[Dict[str, Any]] = ContentUtils.normalize_message(result).content
        block_types: List[str] = []
        for block in blocks:
            block_types.append(block["type"])
        self.assertEqual(block_types, ["reasoning", "text"])
        self.assertEqual(blocks[0]["reasoning"], "Mock thinking.")
        self.assertEqual(blocks[1]["text"], "the answer")
        self.assertEqual(blocks[1]["extras"], {"signature": "mock-thought-signature"})
        self.assertEqual(ContentUtils.flatten_to_text(result), "the answer")
