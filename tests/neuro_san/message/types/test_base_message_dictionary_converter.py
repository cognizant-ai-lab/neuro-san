
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
from typing import Optional

from unittest import TestCase

from langchain_core.messages.ai import AIMessage
from langchain_core.messages.base import BaseMessage
from langchain_core.messages.human import HumanMessage
from langchain_core.messages.system import SystemMessage

from neuro_san.message.types.agent_framework_message import AgentFrameworkMessage
from neuro_san.message.types.agent_message import AgentMessage
from neuro_san.message.types.agent_tool_result_message import AgentToolResultMessage
from neuro_san.message.types.base_message_dictionary_converter import BaseMessageDictionaryConverter
from neuro_san.message.types.chat_message_type import ChatMessageType
from neuro_san.message.utils.content_utils import ContentUtils

from tests.neuro_san.message.content_fixtures import ContentFixtures


# pylint: disable=too-many-public-methods
class TestBaseMessageDictionaryConverter(TestCase):
    """
    Golden-parity tests for the wire converter, plus the text projection
    of list-form (block) content.

    The plain-string tests lock down the EXACT ChatMessage dictionaries
    produced for text-only traffic - the shapes every deployed client sees.
    Every one of them must stay green untouched: byte-identical wire
    output for text-only messages is the backward-compatibility guarantee.

    The list-content tests cover the full text projection of block content:
    the text joins every text block, so thinking-first content gives the
    answer text and list-of-str content gives its joined strings.

    The content_blocks tests cover the outbound content_blocks mapping:
    block content that says more than its text also rides in the
    format-tagged content_blocks wrapper, while text-only content, a lone
    text block included, emits no such key.
    """

    ORIGIN: List[Dict[str, Any]] = [{"tool": "front_man", "instantiation_index": 0}]

    @staticmethod
    def block_types(chat_message: Dict[str, Any]) -> List[str]:
        """
        List the block types a wire dictionary carries.

        :param chat_message: A ChatMessage dictionary produced by to_dict
        :return: The "type" of each block inside its content_blocks wrapper
        """
        types: List[str] = []
        block: Optional[Dict[str, Any]] = None
        for block in chat_message.get("content_blocks", {}).get("blocks", []):
            types.append(block.get("type"))
        return types

    def assert_wrapped_blocks(self, chat_message: Dict[str, Any]) -> None:
        """
        Asserts the content_blocks wrapper shape: the langchain_v1 format tag,
        a non-empty block list, and text equal to the blocks' flattened text.

        :param chat_message: A ChatMessage dictionary produced by to_dict
        """
        wrapper: Dict[str, Any] = chat_message.get("content_blocks")
        self.assertEqual(sorted(wrapper.keys()), ["blocks", "format"])
        self.assertEqual(wrapper.get("format"), ContentUtils.CONTENT_BLOCKS_FORMAT_LANGCHAIN_V1)
        self.assertGreater(len(wrapper.get("blocks")), 0)
        self.assertEqual(ContentUtils.flatten_to_text(wrapper.get("blocks")), chat_message.get("text"))

    def test_to_dict_human_message_exact_shape(self) -> None:
        """
        The wire dict for a HumanMessage is exactly type + origin + text.
        """
        converter = BaseMessageDictionaryConverter(origin=self.ORIGIN)
        result: Dict[str, Any] = converter.to_dict(HumanMessage(content="hello"))
        self.assertEqual(result, {
            "type": ChatMessageType.HUMAN,
            "origin": self.ORIGIN,
            "text": "hello",
        })

    def test_to_dict_ai_message_exact_shape(self) -> None:
        """
        The wire dict for a plain-string AIMessage is exactly type + origin + text.
        """
        converter = BaseMessageDictionaryConverter(origin=self.ORIGIN)
        result: Dict[str, Any] = converter.to_dict(AIMessage(content="the answer"))
        self.assertEqual(result, {
            "type": ChatMessageType.AI,
            "origin": self.ORIGIN,
            "text": "the answer",
        })

    def test_to_dict_system_message_without_origin(self) -> None:
        """
        With no origin configured, the origin key is absent entirely.
        """
        converter = BaseMessageDictionaryConverter()
        result: Dict[str, Any] = converter.to_dict(SystemMessage(content="instructions"))
        self.assertEqual(result, {
            "type": ChatMessageType.SYSTEM,
            "text": "instructions",
        })

    def test_to_dict_agent_tool_result_carries_tool_result_origin(self) -> None:
        """
        AgentToolResultMessage adds its tool_result_origin as a sibling key.
        """
        converter = BaseMessageDictionaryConverter(origin=self.ORIGIN)
        message = AgentToolResultMessage(content="tool says", tool_result_origin=self.ORIGIN)
        result: Dict[str, Any] = converter.to_dict(message)
        self.assertEqual(result, {
            "type": ChatMessageType.AGENT_TOOL_RESULT,
            "origin": self.ORIGIN,
            "text": "tool says",
            "tool_result_origin": self.ORIGIN,
        })

    def test_to_dict_preserves_whitespace_and_empty_string(self) -> None:
        """
        String content is never stripped, and an empty string still produces
        a text key (only None omits it).
        """
        converter = BaseMessageDictionaryConverter()
        padded_result: Dict[str, Any] = converter.to_dict(AIMessage(content="  padded  "))
        self.assertEqual(padded_result.get("text"), "  padded  ")
        empty_result: Dict[str, Any] = converter.to_dict(AIMessage(content=""))
        self.assertEqual(empty_result.get("text"), "")

    def test_from_dict_round_trips_plain_text_messages(self) -> None:
        """
        to_dict -> from_dict round-trips type and text for the langchain
        message types that populate chat history.
        """
        converter = BaseMessageDictionaryConverter()
        originals: List[BaseMessage] = [SystemMessage(content="s"), HumanMessage(content="h"), AIMessage(content="a")]
        original: Optional[BaseMessage] = None
        wire_dict: Optional[Dict[str, Any]] = None
        restored: Optional[BaseMessage] = None
        for original in originals:
            wire_dict = converter.to_dict(original)
            restored = converter.from_dict(wire_dict)
            self.assertIs(type(restored), type(original))
            self.assertEqual(restored.content, original.content)

    def test_from_dict_round_trips_agent_tool_result(self) -> None:
        """
        AgentToolResultMessage round-trips content and tool_result_origin.
        """
        converter = BaseMessageDictionaryConverter()
        original = AgentToolResultMessage(content="tool says", tool_result_origin=self.ORIGIN)
        wire_dict: Dict[str, Any] = converter.to_dict(original)
        restored: BaseMessage = converter.from_dict(wire_dict)
        self.assertIsInstance(restored, AgentToolResultMessage)
        self.assertEqual(restored.content, "tool says")
        self.assertEqual(restored.tool_result_origin, self.ORIGIN)

    def test_from_dict_unknown_type_yields_none_when_langchain_only(self) -> None:
        """
        Non-langchain message types are not restored under the default
        langchain_only=True (they must not enter langchain chat history).
        """
        converter = BaseMessageDictionaryConverter(langchain_only=True)
        self.assertIsNone(converter.from_dict({"type": ChatMessageType.AGENT, "text": "internal"}))

    def test_to_dict_thinking_first_content_yields_answer_text(self) -> None:
        """
        An Anthropic thinking-first response produces the answer text on
        the wire, even though its first block is the thinking block, which
        has no "text".
        """
        converter = BaseMessageDictionaryConverter(origin=self.ORIGIN)
        result: Dict[str, Any] = converter.to_dict(ContentFixtures.anthropic_thinking_first())
        self.assertEqual(sorted(result.keys()), ["content_blocks", "origin", "text", "type"])
        self.assertEqual(result.get("type"), ChatMessageType.AI)
        self.assertEqual(result.get("origin"), self.ORIGIN)
        self.assertEqual(result.get("text"), "the answer")
        # The thinking block rides along as a standard reasoning block.
        self.assert_wrapped_blocks(result)
        self.assertEqual(self.block_types(result), ["reasoning", "text"])

    def test_to_dict_concatenates_all_text_blocks(self) -> None:
        """
        The text comes from the text block even when a reasoning block is
        first, and a reasoning-only message emits text="".
        """
        converter = BaseMessageDictionaryConverter()
        result: Dict[str, Any] = converter.to_dict(ContentFixtures.openai_responses_reasoning())
        self.assertEqual(result.get("type"), ChatMessageType.AI)
        self.assertEqual(result.get("text"), "the answer")
        self.assert_wrapped_blocks(result)
        self.assertEqual(self.block_types(result)[-1], "text")
        self.assertIn("reasoning", self.block_types(result))

        reasoning_only = AIMessage(content=[{"type": "reasoning", "reasoning": "hidden"}])
        self.assertEqual(converter.to_dict(reasoning_only), {
            "type": ChatMessageType.AI,
            "text": "",
            "content_blocks": {
                "format": "langchain_v1",
                "blocks": [{"type": "reasoning", "reasoning": "hidden"}],
            },
        })

    def test_to_dict_list_of_str_content_does_not_crash(self) -> None:
        """
        List-of-strings content, legal per the pydantic annotation, converts
        without an error, and its strings are joined into the text.
        """
        converter = BaseMessageDictionaryConverter()
        result: Dict[str, Any] = converter.to_dict(ContentFixtures.list_of_str())
        # A list of strings has no block structure, so no content_blocks either.
        self.assertEqual(result, {
            "type": ChatMessageType.AI,
            "text": "part one, part two",
        })

    def test_to_dict_empty_list_content_still_omits_text(self) -> None:
        """
        Empty-list content omits the text key (emitting text="" would make
        such messages answer-eligible in AnswerMessageFilter).
        """
        converter = BaseMessageDictionaryConverter()
        result: Dict[str, Any] = converter.to_dict(ContentFixtures.empty_list_content())
        self.assertEqual(result, {
            "type": ChatMessageType.AI,
        })

    def test_to_dict_blank_text_block_keeps_emitting_text(self) -> None:
        """
        Blank-but-non-empty block content emits its (blank) text; only the
        empty LIST omits the text key. Gating omission on "no visible text"
        instead would omit text for reasoning-only messages, changing their
        wire shape.
        """
        converter = BaseMessageDictionaryConverter()
        result: Dict[str, Any] = converter.to_dict(AIMessage(content=[{"type": "text", "text": " "}]))
        self.assertEqual(result, {
            "type": ChatMessageType.AI,
            "text": " ",
        })

    def test_to_dict_agent_framework_message_optionals_exact_shape(self) -> None:
        """
        The optional sibling keys (chat_context, structure, sly_data) pass
        through exactly, alongside type + text.
        """
        chat_context: Dict[str, Any] = {"chat_histories": []}
        structure: Dict[str, Any] = {"key": "value"}
        sly_data: Dict[str, Any] = {"secret": "s"}
        message = AgentFrameworkMessage(content="the answer", chat_context=chat_context,
                                        sly_data=sly_data, structure=structure)
        result: Dict[str, Any] = BaseMessageDictionaryConverter().to_dict(message)
        self.assertEqual(result, {
            "type": ChatMessageType.AGENT_FRAMEWORK,
            "text": "the answer",
            "chat_context": chat_context,
            "structure": structure,
            "sly_data": sly_data,
        })

    def test_to_dict_trivial_text_block_emits_no_content_blocks(self) -> None:
        """
        A lone text block, provider bookkeeping and empty annotations included,
        is plain text on the wire: the same shape as plain-string content.
        """
        converter = BaseMessageDictionaryConverter()
        message = AIMessage(content=[{"type": "text", "text": "hi", "id": "msg_1", "index": 0, "annotations": []}])
        self.assertEqual(converter.to_dict(message), {
            "type": ChatMessageType.AI,
            "text": "hi",
        })

    def test_to_dict_anthropic_tool_use_stays_text_only(self) -> None:
        """
        The most common list content in production, an Anthropic tool-calling
        turn of text + tool_use, has the exact text-only wire shape: tool-call
        blocks are not message content and the lone text block is trivial.
        """
        converter = BaseMessageDictionaryConverter()
        self.assertEqual(converter.to_dict(ContentFixtures.anthropic_tool_use()), {
            "type": ChatMessageType.AI,
            "text": "Let me look that up.",
        })

    def test_to_dict_malformed_block_content_falls_back_to_text(self) -> None:
        """
        Block content the provider translators cannot standardize (here a text
        block with no "text") goes out text-only instead of raising, so the
        journal write that carries it never fails.
        """
        converter = BaseMessageDictionaryConverter()
        message = AIMessage(content=[{"type": "text"}], response_metadata={"model_provider": "anthropic"})
        result: Optional[Dict[str, Any]] = None
        with self.assertLogs("BaseMessageDictionaryConverter", level="WARNING"):
            result = converter.to_dict(message)
        self.assertEqual(result, {
            "type": ChatMessageType.AI,
            "text": "",
        })

    def test_to_dict_blocks_that_lose_text_fall_back_to_text(self) -> None:
        """
        A mixed list of a bare string and blocks: the Anthropic translator
        drops the string, so the blocks would flatten to less than the
        message's text. The message goes out text-only, with a warning, so
        text and content_blocks can never disagree.
        """
        converter = BaseMessageDictionaryConverter()
        message = AIMessage(
            content=[
                "hello ",
                {"type": "thinking", "thinking": "t", "signature": "s"},
                {"type": "text", "text": "world"},
            ],
            response_metadata={"model_provider": "anthropic"})
        result: Optional[Dict[str, Any]] = None
        with self.assertLogs("BaseMessageDictionaryConverter", level="WARNING"):
            result = converter.to_dict(message)
        self.assertEqual(result, {
            "type": ChatMessageType.AI,
            "text": "hello world",
        })

    def test_to_dict_agent_tool_result_with_blocks_emits_content_blocks(self) -> None:
        """
        A tool that returned content blocks is journaled as an
        AgentToolResultMessage with list content; its wire dict carries both
        origins, the flattened text and the wrapper with the blocks intact.
        """
        converter = BaseMessageDictionaryConverter(origin=self.ORIGIN)
        message = AgentToolResultMessage(
            content=[
                {"type": "text", "text": "tool says"},
                {"type": "image", "base64": "aW1n", "mime_type": "image/png"},
            ],
            tool_result_origin=self.ORIGIN)
        self.assertEqual(converter.to_dict(message), {
            "type": ChatMessageType.AGENT_TOOL_RESULT,
            "origin": self.ORIGIN,
            "text": "tool says",
            "tool_result_origin": self.ORIGIN,
            "content_blocks": {
                "format": "langchain_v1",
                "blocks": [
                    {"type": "text", "text": "tool says"},
                    {"type": "image", "base64": "aW1n", "mime_type": "image/png"},
                ],
            },
        })

    def test_to_dict_text_block_with_phase_emits_content_blocks(self) -> None:
        """
        A lone text block carrying a provider key with a value (OpenAI's
        Responses "phase") is not collapsed to plain text, so the key reaches
        clients.
        """
        converter = BaseMessageDictionaryConverter()
        message = AIMessage(
            content=[{"type": "text", "text": "hi", "phase": "final_answer", "id": "msg_1"}],
            response_metadata={"model_provider": "openai", "output_version": "responses/v1"})
        self.assertEqual(converter.to_dict(message), {
            "type": ChatMessageType.AI,
            "text": "hi",
            "content_blocks": {
                "format": "langchain_v1",
                "blocks": [{"type": "text", "text": "hi", "phase": "final_answer", "id": "msg_1"}],
            },
        })

    def test_to_dict_standard_blocks_emit_exact_wrapper(self) -> None:
        """
        Already-standard v1 blocks pass through into the wrapper unchanged,
        with text as their flattened projection.
        """
        converter = BaseMessageDictionaryConverter(origin=self.ORIGIN)
        message = AIMessage(content=[{"type": "reasoning", "reasoning": "r"}, {"type": "text", "text": "hi"}])
        self.assertEqual(converter.to_dict(message), {
            "type": ChatMessageType.AI,
            "origin": self.ORIGIN,
            "text": "hi",
            "content_blocks": {
                "format": "langchain_v1",
                "blocks": [{"type": "reasoning", "reasoning": "r"}, {"type": "text", "text": "hi"}],
            },
        })

    def test_to_dict_multimodal_human_emits_content_blocks(self) -> None:
        """
        A HumanMessage with text and image blocks, as a multimodal client will
        send, is echoed with its text plus the blocks, base64 payloads intact.
        """
        converter = BaseMessageDictionaryConverter()
        self.assertEqual(converter.to_dict(ContentFixtures.multimodal_human()), {
            "type": ChatMessageType.HUMAN,
            "text": "Describe this image.",
            "content_blocks": {
                "format": "langchain_v1",
                "blocks": [
                    {"type": "text", "text": "Describe this image."},
                    {"type": "image", "base64": "aW1hZ2UtYnl0ZXM=", "mime_type": "image/png"},
                ],
            },
        })

    def test_from_dict_restores_agent_types_when_not_langchain_only(self) -> None:
        """
        With langchain_only=False the internal AGENT/AGENT_FRAMEWORK types
        are restored with their text (and structure for AGENT).
        """
        converter = BaseMessageDictionaryConverter(langchain_only=False)
        structure: Dict[str, Any] = {"key": "value"}
        agent_dict: Dict[str, Any] = {"type": ChatMessageType.AGENT, "text": "thinking", "structure": structure}
        agent: BaseMessage = converter.from_dict(agent_dict)
        self.assertIsInstance(agent, AgentMessage)
        self.assertEqual(agent.content, "thinking")
        self.assertEqual(agent.structure, structure)

        framework: BaseMessage = converter.from_dict({"type": ChatMessageType.AGENT_FRAMEWORK, "text": "answer"})
        self.assertIsInstance(framework, AgentFrameworkMessage)
        self.assertEqual(framework.content, "answer")
