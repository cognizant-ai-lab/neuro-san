
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
"""
See class comment for details
"""
import aiofiles
from leaf_common.serialization.util.bytes_decoder import BytesDecoder


class TextFileReader:
    """
    Class providing utility methods for reading text files in several possible encodings.
    """

    @staticmethod
    def read_text_file(filepath: str) -> str:
        """
        Read the content of a text file in some encoding and return it as a string.
        :param filepath: The path to the text file to read
        :return: The content of the text file as a string
        """
        with open(filepath, "rb") as binary_file:
            contents: bytes = binary_file.read()
            text, _ = BytesDecoder.decode_bytes(contents, source_name=filepath)
            return text

    @staticmethod
    async def async_read_text_file(self, filepath: str) -> str:
        """
        Asynchronously read the content of a text file in some encoding and return it as a string.
        :param filepath: The path to the text file to read
        :return: The content of the text file as a string
        """
        async with aiofiles.open(filepath, "rb") as binary_file:
            contents: bytes = await binary_file.read()
            text, _ = BytesDecoder.decode_bytes(contents, source_name=filepath)
            return text
