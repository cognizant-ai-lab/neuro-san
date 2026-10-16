
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
from unittest import TestCase
from unittest.mock import MagicMock
from unittest.mock import patch

from langchain_core.messages.ai import AIMessage
from langchain_core.messages.base import BaseMessage

from neuro_san.message.content_blocks.content_blocks_format import ContentBlocksFormat
from neuro_san.message.content_blocks.content_blocks_format_registry import ContentBlocksFormatRegistry


class TestContentBlocksFormatRegistry(TestCase):
    """
    Tests for the lookup of a content_blocks format by its wire name or by
    the mark a message carries.
    """

    def test_default_is_langchain_v1(self) -> None:
        """
        The server writes langchain_v1 wrappers.
        """
        default_format: ContentBlocksFormat = ContentBlocksFormatRegistry.get_default()
        self.assertEqual(default_format.get_name(), "langchain_v1")

    def test_get_format_known_name(self) -> None:
        """
        A known name finds the one shared format instance.
        """
        found: ContentBlocksFormat = ContentBlocksFormatRegistry.get_format("langchain_v1")
        self.assertIs(found, ContentBlocksFormatRegistry.get_default())

    def test_get_format_unknown_or_non_string_is_none(self) -> None:
        """
        Unknown names and anything that is not a string name no format.
        A client can send any JSON value as the format, so non-hashable
        values must not raise.
        """
        unknown: List[Any] = ["somebody_elses_v2", "", None, 42, {}, ["langchain_v1"]]
        # Each value names no format and must not raise.
        value: Any = None
        for value in unknown:
            with self.subTest(value=str(value)):
                self.assertIsNone(ContentBlocksFormatRegistry.get_format(value))

    def test_format_for_message_follows_the_mark(self) -> None:
        """
        A message marked by a format is handled by that format. A message
        with no mark, or with a mark no format knows, falls to the default.
        A second format is registered for the test, so that following the
        mark and falling to the default give different answers.
        """
        default_format: ContentBlocksFormat = ContentBlocksFormatRegistry.get_default()
        other_format: MagicMock = MagicMock(spec=ContentBlocksFormat)
        other_format.is_format_of.side_effect = partial(self.is_marked_with, "v9")

        marked_default: AIMessage = AIMessage(content="a", response_metadata={"output_version": "v1"})
        marked_other: AIMessage = AIMessage(content="a", response_metadata={"output_version": "v9"})
        unmarked: AIMessage = AIMessage(content="a", response_metadata={"model_provider": "openai"})
        unknown_mark: AIMessage = AIMessage(content="a", response_metadata={"output_version": "v99"})
        with patch.dict(ContentBlocksFormatRegistry.FORMATS, {"other_v9": other_format}):
            self.assertIs(ContentBlocksFormatRegistry.format_for_message(marked_default), default_format)
            self.assertIs(ContentBlocksFormatRegistry.format_for_message(marked_other), other_format)
            self.assertIs(ContentBlocksFormatRegistry.format_for_message(unmarked), default_format)
            self.assertIs(ContentBlocksFormatRegistry.format_for_message(unknown_mark), default_format)

    @staticmethod
    def is_marked_with(version: str, message: BaseMessage) -> bool:
        """
        Stand-in for a format's is_format_of.

        :param version: The output_version value the stand-in format claims as its mark
        :param message: The BaseMessage to inspect
        :return: True if the message carries that output_version
        """
        response_metadata: Dict[str, Any] = message.response_metadata
        return response_metadata.get("output_version") == version
