
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
from typing import List

from unittest import TestCase

from neuro_san.message.content_blocks.content_blocks_format import ContentBlocksFormat
from neuro_san.message.content_blocks.content_blocks_format_registry import ContentBlocksFormatRegistry


class TestContentBlocksFormatRegistry(TestCase):
    """
    Tests for the lookup of a content_blocks format by its wire name.
    """

    def test_default_is_langchain_v1(self) -> None:
        """
        The server writes langchain_v1 wrappers.
        """
        default_format: ContentBlocksFormat = ContentBlocksFormatRegistry.get_default()
        self.assertEqual(default_format.get_name(), "langchain_v1")

    def test_get_known_format(self) -> None:
        """
        A known name finds the one shared format instance.
        """
        found: ContentBlocksFormat = ContentBlocksFormatRegistry.get("langchain_v1")
        self.assertIs(found, ContentBlocksFormatRegistry.get_default())

    def test_get_unknown_or_non_string_is_none(self) -> None:
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
                self.assertIsNone(ContentBlocksFormatRegistry.get(value))
