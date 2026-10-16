
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
from typing import Optional

from neuro_san.message.content_blocks.content_blocks_format import ContentBlocksFormat
from neuro_san.message.content_blocks.langchain_v1_content_blocks_format import LangchainV1ContentBlocksFormat


class ContentBlocksFormatRegistry:
    """
    Finds the ContentBlocksFormat for a content_blocks wrapper's "format"
    string.

    Adding a format means adding its class and one entry in FORMATS here.
    The default format is the one the server writes when it builds a
    wrapper itself.
    """

    DEFAULT_FORMAT: ContentBlocksFormat = LangchainV1ContentBlocksFormat()

    FORMATS: Dict[str, ContentBlocksFormat] = {
        DEFAULT_FORMAT.get_name(): DEFAULT_FORMAT,
    }

    @staticmethod
    def get_default() -> ContentBlocksFormat:
        """
        Find the format the server writes when it builds a wrapper itself.

        :return: The format the server writes
        """
        return ContentBlocksFormatRegistry.DEFAULT_FORMAT

    @staticmethod
    def get_format(format_name: Any) -> Optional[ContentBlocksFormat]:
        """
        Find the format a wrapper's "format" value names.

        :param format_name: The "format" value of a content_blocks wrapper.
                Anything but a string names no format.
        :return: The format, or None when this server does not know it
        """
        if not isinstance(format_name, str):
            return None
        return ContentBlocksFormatRegistry.FORMATS.get(format_name)
