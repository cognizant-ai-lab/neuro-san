
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
from __future__ import annotations

from typing import Any
from typing import Dict

from leaf_common.utils.interface import interface

from neuro_san.interfaces.async_agent_session import AsyncAgentSession
from neuro_san.interfaces.reservation import Reservation


@interface
class ActivationCapsule:
    """
    An interface that allows CodedTools and middleware to call other agents
    and to create LLM model instances.

    Instances get handed down via the CodedTool's arguments dictionary via the
    "activation_capsule" key via the invoke() or async_invoke() methods.

    We expect its use within a CodedTool's async_invoke() to be:

        activation_capsule: ActivationCapsule = args.get("activation_capsule")
        result: str = await activation_capsule.use_tool("my_agent", {"input": "Hello"}, sly_data)

    Resources created through an ActivationCapsule are released by the agent framework,
    so callers do not need to close them.
    """

    async def use_tool(self, tool_name: str, tool_args: Dict[str, Any], sly_data: Dict[str, Any]) -> str:
        """
        Calls a tool or agent by name.

        :param tool_name: The name of the tool to invoke
        :param tool_args: A dictionary of arguments to send to the tool.
        :param sly_data: private data dictionary to send to the tool.
        :return: A string representing the last received content text of the last message.
        """
        raise NotImplementedError

    async def use_reservation(self, reservation: Reservation, args: Dict[str, Any], sly_data: Dict[str, Any]) -> str:
        """
        Calls a reserved temporary agent network.

        :param reservation: The Reservation to invoke
        :param args: A dictionary of arguments to send to the reserved temporary network.
        :param sly_data: private data dictionary to send to the reserved temporary network.
        :return: A string representing the last received content text of the last message.
        """
        raise NotImplementedError

    def create_chat_model(self, llm_config: Dict[str, Any], sly_data: Dict[str, Any], num_fallbacks: int = None) -> Any:
        """
        Creates an LLM model instance.

        :param llm_config: The llm config dictionary
        :param sly_data: The private sly_data dictionary. This is needed for bring-your-own-key scenarios.
        :param num_fallbacks: The number of fallbacks to try. Default value of None implies all.
        :return: The llm model to use given the context type (usually langchain)
        :raises ValueError: If the LLM cannot be created from the llm_config and sly_data.
        """
        raise NotImplementedError

    async def create_session(self, agent_name: str) -> AsyncAgentSession:
        """
        Creates an AsyncAgentSession for an external agent network.

        Note: Use use_tool() to invoke agents either internal or external to the graph.

        The session provided here is to be used for agent metadata such as function() and connectivity().
        Chatting through its streaming_chat() skips the framework's policies that use_tool() applies,
        especially those surrounding sly_data and message journaling.

        The session is owned by the capsule and closed by the agent framework,
        so callers do not need to close it.

        :param agent_name: A reference to an external agent network, either
                    "/<agent_name>" for an agent network on the same server
                    or a full url, as it would appear in an agent spec's tools list.
        :return: An AsyncAgentSession for the agent network
        :raises ValueError: If agent_name is not an external agent reference,
                    or no session can be created for it.
        """
        raise NotImplementedError
