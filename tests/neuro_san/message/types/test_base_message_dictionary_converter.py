
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


class TestBaseMessageDictionaryConverter:
    """
    Golden-parity tests for the wire converter.

    These lock down the EXACT ChatMessage dictionaries produced for
    plain-string traffic - the shapes every deployed client sees today.
    The content-block work (see issue #1222) must keep every test here
    green untouched: byte-identical wire output for text-only messages
    is the backward-compatibility guarantee of that whole effort.

    Deliberately absent: list-form (block) content through to_dict. Its
    current behavior is the bug being fixed (thinking-first content
    flattens to "", list-of-str crashes), so there is nothing to lock.
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
