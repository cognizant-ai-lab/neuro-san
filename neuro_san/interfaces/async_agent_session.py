
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
from typing import Generator

from neuro_san.interfaces.agent_session_constants import AgentSessionConstants


class AsyncAgentSession(AgentSessionConstants):
    """
    Asynchronous interface for the initiation and continuity of a single Agent session.
    """

    async def function(self, request_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        :param request_dict: A dictionary version of the FunctionRequest
                    protobufs structure. Has the following keys:
                        <None>
        :return: A dictionary version of the FunctionResponse
                    protobufs structure. Has the following keys:
                "function" - the dictionary description of the function
        """
        raise NotImplementedError

    async def connectivity(self, request_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        :param request_dict: A dictionary version of the ConnectivityRequest
                    protobufs structure. Has the following keys:
                        <None>
        :return: A dictionary version of the ConnectivityResponse
                    protobufs structure. Has the following keys:
                "connectivity_info" - the list of connectivity descriptions for
                                    each node in the agent network the service
                                    wants the client ot know about.
        """
        raise NotImplementedError

    async def streaming_chat(self, request_dict: Dict[str, Any]) -> Generator[Dict[str, Any], None, None]:
        """
        :param request_dict: A dictionary version of the ChatRequest
                    protobufs structure. Has the following keys:
            "user_message" - A ChatMessage dict representing the user input to the chat stream
            "chat_context" - A ChatContext dict representing the state of the previous conversation
                            (if any)

        :return: An iterator of dictionary versions of the ChatResponse
                    protobufs structure. Has the following keys:
            "response"      - An optional ChatMessage dictionary.  See chat.proto for details.

            Note that responses to the chat input might be numerous and will come as they
            are produced until the system decides there are no more messages to be sent.
        """
        raise NotImplementedError

    def close(self):
        """
        Close the session, releasing any underlying client connection.

        For remote sessions this drops the client connection to the service and
        unblocks an in-flight streaming_chat() on the client side. It does NOT
        directly cancel the server-side work: the neuro-san service ends the
        corresponding request only when it next detects the dropped connection --
        that is, on its next result or heartbeat flush. So termination is prompt
        while the service is streaming results (or a keep-alive heartbeat is
        enabled), but a request that produces no output, with heartbeat and
        request-timeout disabled, may keep running server-side until it does.
        In short: close() guarantees release of the client connection, not
        immediate server-side termination.

        This is a synchronous method (no await needed) so it can be invoked from
        a supervising sync context or another thread; implementations that own an
        event-loop-bound client schedule the actual close on that loop.
        Safe to call more than once.

        A remote session is single-use with respect to close(): once closed it
        cannot be reused -- subsequent streaming_chat(), function() and
        connectivity() calls raise AgentSessionClosedError (see is_closed()).

        The default implementation is a no-op: sessions that hold no external
        connection (e.g. in-process direct sessions) have nothing to close and
        are never considered closed.
        """
        return

    def is_closed(self) -> bool:
        """
        :return: True if close() has been called on this session, in which case
                 further streaming_chat()/function()/connectivity() calls raise
                 AgentSessionClosedError. The default is False for sessions that
                 hold no external connection and therefore cannot be closed.
        """
        return False
