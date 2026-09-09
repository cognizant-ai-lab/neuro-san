
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

from neuro_san.internals.chat.chat_history_message_processor import ChatHistoryMessageProcessor
from neuro_san.message.types.chat_message_type import ChatMessageType


class TestChatHistoryMessageProcessor:
    """
    Tests for ChatHistoryMessageProcessor.escape_message.

    The escaping is only meaningful for str text. Every dictionary the
    processor sees today comes from BaseMessageDictionaryConverter.to_dict,
    which always emits str text, so the non-str guard is defensive; these
    tests lock the str behavior and the pass-through for anything else.
    """

    def test_escape_message_escapes_braces_in_str_text(self) -> None:
        """
        Braces in str text are normalized to the doubled, template-safe form,
        whether or not they were already escaped.
        """
        processor: ChatHistoryMessageProcessor = ChatHistoryMessageProcessor()
        original: Dict[str, Any] = {"type": ChatMessageType.AI, "text": "a {b} and {{c}}"}

        result: Dict[str, Any] = processor.escape_message(original)

        assert result["text"] == "a {{b}} and {{c}}"
        assert result["type"] == ChatMessageType.AI
        # The input dictionary is copied, never mutated.
        assert original["text"] == "a {b} and {{c}}"

    def test_escape_message_without_text_returns_none(self) -> None:
        """
        A message with no text key at all is dropped from the history.
        """
        processor: ChatHistoryMessageProcessor = ChatHistoryMessageProcessor()
        assert processor.escape_message({"type": ChatMessageType.AI}) is None

    def test_escape_message_passes_non_str_text_through(self) -> None:
        """
        Non-str text (block content) cannot be brace-escaped, so the message
        is passed through untouched rather than dropped or crashed on.
        """
        processor: ChatHistoryMessageProcessor = ChatHistoryMessageProcessor()
        blocks: List[Dict[str, Any]] = [{"type": "text", "text": "{not escaped}"}]
        original: Dict[str, Any] = {"type": ChatMessageType.AI, "text": blocks}

        result: Dict[str, Any] = processor.escape_message(original)

        assert result is not original
        assert result["text"] is blocks
        assert result["type"] == ChatMessageType.AI
