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

class DecodeUtils:
    """
    Utility class for decoding bytes or bytearrays for funnelling to a common policy point.
    """

    @staticmethod
    def decode(instring: bytearray | bytes, encoding: str = "utf-8") -> str:
        """
        :param instring: The bytes or bytearray to decode
        :param encoding: The encoding to use
        :return: The decoded string
        """
        if not instring:
            return ""

        decoded: str = instring.decode(encoding)
        return decoded
