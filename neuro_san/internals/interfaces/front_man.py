
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

from neuro_san.internals.interfaces.invocation_context import InvocationContext
from neuro_san.internals.interfaces.lingering_resource import LingeringResource


class FrontMan(LingeringResource):
    """
    Interface that describes how a chat interface can interact with a FrontMan
    """

    async def create_any_resources(self):
        """
        Creates resources that will be used throughout the lifetime of the component.
        """
        raise NotImplementedError

    def update_invocation_context(self, invocation_context: InvocationContext):
        """
        Update internal state based on the InvocationContext instance passed in.
        :param invocation_context: The context policy container that pertains to the invocation
        """
        raise NotImplementedError

    def get_origin(self) -> List[Dict[str, Any]]:
        """
        :return: A List of origin dictionaries indicating the origin of the run.
                The origin can be considered a path to the original call to the front-man.
                Origin dictionaries themselves each have the following keys:
                    "tool"                  The string name of the tool in the spec
                    "instantiation_index"   An integer indicating which incarnation
                                            of the tool is being dealt with.
        """
        raise NotImplementedError

    def get_agent_tool_spec(self) -> Dict[str, Any]:
        """
        :return: the dictionary describing the data-driven agent
        """
        raise NotImplementedError

    async def submit_message(self, user_input: str) -> List[BaseMessage]:
        """
        Entry-point method for callers of the root of the Activation tree.

        :param user_input: An input string from the user.
        :return: A list of response messages for the run
        """
        raise NotImplementedError

    async def close_of_request(self, parent_resource: LingeringResource = None):
        """
        Release resources owned by this context when the request is complete.
        This can happen earlier than when the work is complete.

        :param parent_resource: parent resource, if any
        """
        raise NotImplementedError

    async def close_of_work(self, parent_resource: LingeringResource = None):
        """
        Release resources owned by this context when the work is all done.
        This can happen later than when the request is complete.

        :param parent_resource: parent resource, if any. Expected to be the
                RunContext which contains the scope of operation of this CallableActivation
        """
        raise NotImplementedError
