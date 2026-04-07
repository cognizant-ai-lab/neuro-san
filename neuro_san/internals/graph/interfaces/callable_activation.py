
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

from langchain_core.messages.base import BaseMessage

from neuro_san.internals.interfaces.lingering_resource import LingeringResource
from neuro_san.internals.run_context.interfaces.run_context import RunContext


class CallableActivation(LingeringResource):
    """
    Interface describing what a CallingActivation can access
    when invoking LLM function calls.
    """

    async def build(self) -> BaseMessage:
        """
        Main entry point to the class.

        :return: A BaseMessage produced during this process.
        """
        raise NotImplementedError

    def get_origin(self) -> List[Dict[str, Any]]:
        """
        :return: A List of origin dictionaries indicating the origin of the tool.
                The origin can be considered a path to the original call to the front-man.
                Origin dictionaries themselves each have the following keys:
                    "tool"                  The string name of the tool in the spec
                    "instantiation_index"   An integer indicating which incarnation
                                            of the tool is being dealt with.
        """
        raise NotImplementedError

    async def close_of_request(self, parent_resource: RunContext = None):
        """
        Release resources owned by this context when the request is complete.
        This can happen earlier than when the work is complete.

        :param parent_resource: parent resource, if any
        """
        # Do nothing by default for easier implementation inheritance

    async def close_of_work(self, parent_resource: RunContext = None):
        """
        Release resources owned by this context when the work is all done.
        This can happen later than when the request is complete.

        :param parent_resource: parent resource, if any
        """
        raise NotImplementedError
