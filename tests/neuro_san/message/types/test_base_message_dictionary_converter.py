
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

from langchain_core.messages.ai import AIMessage
from langchain_core.messages.human import HumanMessage
from langchain_core.messages.system import SystemMessage

from neuro_san.message.types.agent_framework_message import AgentFrameworkMessage
from neuro_san.message.types.agent_message import AgentMessage
from neuro_san.message.types.agent_tool_result_message import AgentToolResultMessage
from neuro_san.message.types.base_message_dictionary_converter import BaseMessageDictionaryConverter
from neuro_san.message.types.chat_message_type import ChatMessageType

from tests.neuro_san.message.content_fixtures import ContentFixtures


class TestBaseMessageDictionaryConverter:
    """
    Golden-parity tests for the wire converter, plus the corrected
    projection of list-form (block) content.

    The plain-string tests lock down the EXACT ChatMessage dictionaries
    produced for text-only traffic - the shapes every deployed client sees.
    The content-block work (see issue #1222) must keep every one of them
    green untouched: byte-identical wire output for text-only messages
    is the backward-compatibility guarantee of that whole effort.

    The list-content tests cover the wire-flatten fix: the full text
    projection replaces the old first-block-only flatten that produced ""
    for thinking-first content and crashed on list-of-str.
    """

    ORIGIN = [{"tool": "front_man", "instantiation_index": 0}]

    def test_to_dict_human_message_exact_shape(self):
        """
        The wire dict for a HumanMessage is exactly type + origin + text.
        """
        converter = BaseMessageDictionaryConverter(origin=self.ORIGIN)
        result = converter.to_dict(HumanMessage(content="hello"))
        assert result == {
            "type": ChatMessageType.HUMAN,
            "origin": self.ORIGIN,
            "text": "hello",
        }

    def test_to_dict_ai_message_exact_shape(self):
        """
        The wire dict for a plain-string AIMessage is exactly type + origin + text.
        """
        converter = BaseMessageDictionaryConverter(origin=self.ORIGIN)
        result = converter.to_dict(AIMessage(content="the answer"))
        assert result == {
            "type": ChatMessageType.AI,
            "origin": self.ORIGIN,
            "text": "the answer",
        }

    def test_to_dict_system_message_without_origin(self):
        """
        With no origin configured, the origin key is absent entirely.
        """
        converter = BaseMessageDictionaryConverter()
        result = converter.to_dict(SystemMessage(content="instructions"))
        assert result == {
            "type": ChatMessageType.SYSTEM,
            "text": "instructions",
        }

    def test_to_dict_agent_tool_result_carries_tool_result_origin(self):
        """
        AgentToolResultMessage adds its tool_result_origin as a sibling key.
        """
        converter = BaseMessageDictionaryConverter(origin=self.ORIGIN)
        message = AgentToolResultMessage(content="tool says", tool_result_origin=self.ORIGIN)
        result = converter.to_dict(message)
        assert result == {
            "type": ChatMessageType.AGENT_TOOL_RESULT,
            "origin": self.ORIGIN,
            "text": "tool says",
            "tool_result_origin": self.ORIGIN,
        }

    def test_to_dict_preserves_whitespace_and_empty_string(self):
        """
        String content is never stripped, and an empty string still produces
        a text key (only None omits it).
        """
        converter = BaseMessageDictionaryConverter()
        assert converter.to_dict(AIMessage(content="  padded  "))["text"] == "  padded  "
        assert converter.to_dict(AIMessage(content=""))["text"] == ""

    def test_from_dict_round_trips_plain_text_messages(self):
        """
        to_dict -> from_dict round-trips type and text for the langchain
        message types that populate chat history.
        """
        converter = BaseMessageDictionaryConverter()
        for original in [SystemMessage(content="s"), HumanMessage(content="h"), AIMessage(content="a")]:
            restored = converter.from_dict(converter.to_dict(original))
            assert type(restored) is type(original)
            assert restored.content == original.content

    def test_from_dict_round_trips_agent_tool_result(self):
        """
        AgentToolResultMessage round-trips content and tool_result_origin.
        """
        converter = BaseMessageDictionaryConverter()
        original = AgentToolResultMessage(content="tool says", tool_result_origin=self.ORIGIN)
        restored = converter.from_dict(converter.to_dict(original))
        assert isinstance(restored, AgentToolResultMessage)
        assert restored.content == "tool says"
        assert restored.tool_result_origin == self.ORIGIN

    def test_from_dict_unknown_type_yields_none_when_langchain_only(self):
        """
        Non-langchain message types are not restored under the default
        langchain_only=True (they must not enter langchain chat history).
        """
        converter = BaseMessageDictionaryConverter(langchain_only=True)
        assert converter.from_dict({"type": ChatMessageType.AGENT, "text": "internal"}) is None

    def test_to_dict_thinking_first_content_yields_answer_text(self):
        """
        THE headline fix: an Anthropic thinking-first response must produce
        the answer text on the wire. The old first-block flatten produced ""
        because the first block is the thinking block, which has no "text".
        """
        converter = BaseMessageDictionaryConverter(origin=self.ORIGIN)
        result = converter.to_dict(ContentFixtures.anthropic_thinking_first())
        assert result == {
            "type": ChatMessageType.AI,
            "origin": self.ORIGIN,
            "text": "the answer",
        }

    def test_to_dict_concatenates_all_text_blocks(self):
        """
        Text blocks after the first must not be dropped, and a reasoning-only
        message still emits text="" exactly as the old flatten did.
        """
        converter = BaseMessageDictionaryConverter()
        result = converter.to_dict(ContentFixtures.openai_responses_reasoning())
        assert result == {
            "type": ChatMessageType.AI,
            "text": "the answer",
        }

        reasoning_only = AIMessage(content=[{"type": "reasoning", "reasoning": "hidden"}])
        assert converter.to_dict(reasoning_only) == {
            "type": ChatMessageType.AI,
            "text": "",
        }

    def test_to_dict_list_of_str_content_does_not_crash(self):
        """
        List-of-strings content is legal per the pydantic annotation and
        raised AttributeError in the old flatten.
        """
        converter = BaseMessageDictionaryConverter()
        result = converter.to_dict(ContentFixtures.list_of_str())
        assert result == {
            "type": ChatMessageType.AI,
            "text": "part one, part two",
        }

    def test_to_dict_blank_block_content_keeps_emitting_text(self):
        """
        Non-empty list content with no visible text keeps emitting the text
        key, exactly as the old flatten did (value[0].get("text", "") always
        produced a string). Such messages are answer-eligible on the wire
        today, and this fix must not change that in either direction:
        only the empty *list* omits the key.
        """
        converter = BaseMessageDictionaryConverter()
        blank_block = AIMessage(content=[{"type": "text", "text": " "}])
        assert converter.to_dict(blank_block) == {
            "type": ChatMessageType.AI,
            "text": " ",
        }

    def test_to_dict_empty_list_content_still_omits_text(self):
        """
        Empty-list content keeps omitting the text key (emitting text=""
        would make such messages newly answer-eligible in AnswerMessageFilter).
        """
        converter = BaseMessageDictionaryConverter()
        result = converter.to_dict(ContentFixtures.empty_list_content())
        assert result == {
            "type": ChatMessageType.AI,
        }

    def test_to_dict_blank_text_block_keeps_emitting_text(self):
        """
        Blank-but-non-empty block content keeps emitting its (blank) text,
        exactly as the old first-block flatten did - only the empty LIST
        omits the text key. Gating omission on "no visible text" instead
        would newly omit text for reasoning-only messages, changing their
        wire shape.
        """
        converter = BaseMessageDictionaryConverter()
        result = converter.to_dict(AIMessage(content=[{"type": "text", "text": " "}]))
        assert result == {
            "type": ChatMessageType.AI,
            "text": " ",
        }

    def test_to_dict_agent_framework_message_optionals_exact_shape(self):
        """
        The optional sibling keys (chat_context, structure, sly_data) pass
        through exactly, alongside type + text.
        """
        chat_context = {"chat_histories": []}
        structure = {"key": "value"}
        sly_data = {"secret": "s"}
        message = AgentFrameworkMessage(content="the answer", chat_context=chat_context,
                                        sly_data=sly_data, structure=structure)
        result = BaseMessageDictionaryConverter().to_dict(message)
        assert result == {
            "type": ChatMessageType.AGENT_FRAMEWORK,
            "text": "the answer",
            "chat_context": chat_context,
            "structure": structure,
            "sly_data": sly_data,
        }

    def test_from_dict_restores_agent_types_when_not_langchain_only(self):
        """
        With langchain_only=False the internal AGENT/AGENT_FRAMEWORK types
        are restored with their text (and structure for AGENT).
        """
        converter = BaseMessageDictionaryConverter(langchain_only=False)
        structure = {"key": "value"}
        agent = converter.from_dict(
            {"type": ChatMessageType.AGENT, "text": "thinking", "structure": structure})
        assert isinstance(agent, AgentMessage)
        assert agent.content == "thinking"
        assert agent.structure == structure

        framework = converter.from_dict(
            {"type": ChatMessageType.AGENT_FRAMEWORK, "text": "answer"})
        assert isinstance(framework, AgentFrameworkMessage)
        assert framework.content == "answer"
