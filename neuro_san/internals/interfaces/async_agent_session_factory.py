
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

from neuro_san.interfaces.async_agent_session import AsyncAgentSession


class AsyncAgentSessionFactory:
    """
    Creates asynchronous AsyncAgentSessions for external agents.
    """

    def create_session(self, agent_url: str, invocation_context: Any, invocation: str = None) -> AsyncAgentSession:
        """
        :param agent_url: A url string pointing to an external agent that came from
                    a tools list in an agent spec.
        :param invocation_context: The context policy container that pertains to the invocation
                    of the agent.

                    Note: At this interface level we are typing this as Any to avoid
                    an import cycle.  This will always be an InvocationContext.

        :param invocation: String describing how the agent wants to be invoked.
                            Can be: "chatbot" - implies waiting for an answer.
                                    "event" - implies no answer needed
                                    None - implies chatbot

        :return: An implementation of AsyncAgentSession through which
                 communications about external agents can be made.
        """
        raise NotImplementedError

    def is_use_direct(self) -> bool:
        """
        :return: When True, will use a Direct session for external agents that would reside on the same server.
        """
        raise NotImplementedError
