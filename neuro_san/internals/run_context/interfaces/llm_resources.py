
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

from abc import abstractmethod

from leaf_common.utils.interface import interface

from neuro_san.internals.interfaces.lingering_resource import LingeringResource


@interface
class LlmResources(LingeringResource):
    """
    A LingeringResource extension for LLM resources
    """
    @abstractmethod
    def get_model(self) -> Any:
        """
        Get the model
        """
        raise NotImplementedError

    @abstractmethod
    async def close_of_request(self, parent_resource: LingeringResource = None):
        """
        Release resources owned by this context when the request is complete.
        This can happen earlier than when the work is complete.

        :param parent_resource: parent resource, if any
        """
        # Do nothing by default for easier implementation inheritance

    @abstractmethod
    async def close_of_work(self, parent_resource: LingeringResource = None):
        """
        Release resources owned by this context when the work is all done.
        This can happen later than when the request is complete.

        :param parent_resource: parent resource, if any
        """
        # Do nothing by default for easier implementation inheritance
