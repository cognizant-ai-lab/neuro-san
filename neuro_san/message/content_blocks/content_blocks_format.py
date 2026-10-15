
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


class ContentBlocksFormat:
    """
    An interface for one format of the blocks a ChatMessage carries in
    content_blocks (see ContentBlocks in chat.proto).

    The wrapper's "format" string names the schema of its "blocks" list.
    Everything the server does that depends on that schema goes through an
    implementation of this interface, found by name in
    ContentBlocksFormatRegistry, so that a new format is a new class and
    not a change to the places that use blocks.
    """

    def get_name(self) -> str:
        """
        Give the name this format has on the wire.

        :return: The "format" value that names this format on the wire
        """
        raise NotImplementedError

    def is_block_list(self, value: Any) -> bool:
        """
        Determine whether a value is a non-empty list of blocks in this
        format that can be used as message content.

        :param value: Any value to inspect
        :return: True if every element is a block this format accepts as content
        """
        raise NotImplementedError

    def restore_blocks(self, blocks: List[Any]) -> List[Dict[str, Any]]:
        """
        Keep the blocks of an inbound list that are well-formed and that a
        model can be given again as message content, and drop the rest.

        :param blocks: The "blocks" list of an inbound content_blocks wrapper
        :return: The blocks to use as message content, in order. Can be empty.
        """
        raise NotImplementedError
