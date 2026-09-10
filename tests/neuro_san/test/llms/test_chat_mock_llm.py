
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

from langchain_core.messages.human import HumanMessage

from neuro_san.message.utils.content_utils import ContentUtils
from neuro_san.test.llms.chat_mock_llm import ChatMockLlm

from tests.neuro_san.message.content_fixtures import ContentFixtures


class TestChatMockLlm:
    """
    Tests for the block-aware behaviors of the mock chat model:
    the plain-string echo is unchanged, list-of-blocks input does not crash
    token counting or streaming, and the THINKING_MARKER hook produces
    Anthropic-style thinking-first block content for keyless testing.
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

    def test_thinking_marker_emits_thinking_first_blocks(self):
        """
        The marker makes _generate respond like ChatAnthropic with extended
        thinking: a thinking block first, then the text answer, with
        model_provider stamped so standardization translates it.
        """
        llm = self.make_llm()
        result = llm.invoke([HumanMessage(content="emit thinking: the answer")])

        assert isinstance(result.content, list)
        assert result.content[0]["type"] == "thinking"
        assert result.response_metadata["model_provider"] == "anthropic"

        blocks = ContentUtils.standard_blocks(result)
        assert [block["type"] for block in blocks] == ["reasoning", "text"]
        assert blocks[1]["text"] == "the answer"
        assert ContentUtils.flatten_to_text(result) == "the answer"
