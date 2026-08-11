
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

from neuro_san.interfaces.agent_session import AgentSession
from neuro_san.internals.interfaces.async_agent_session_factory import AsyncAgentSessionFactory
from neuro_san.internals.interfaces.invocation_context import InvocationContext


class ExternalToolAdapter:
    """
    Class handles setting up a connection to an external agent server
    so that its agents can be used as tools.
    """

    def __init__(self, session_factory: AsyncAgentSessionFactory, agent_url: str):
        """
        Constructor

        :param agent_url: The URL describing where to find the desired agent.
        """

        self.agent_url: str = agent_url
        self.session_factory: AsyncAgentSessionFactory = session_factory
        self.function_json: Dict[str, Any] = None

    async def get_function_json(self, invocation_context: InvocationContext) -> Dict[str, Any]:
        """
        :param invocation_context: The context policy container that pertains to the invocation
        :return: The function json for the agent, as specified by the external agent.
        """
        if self.function_json is None:

            # Lazily get the information about the service
            session: AgentSession = self.session_factory.create_session(self.agent_url,
                                                                        invocation_context=invocation_context)

            # Set up the request. Turns out we don't need much.
            request_dict: Dict[str, Any] = {}

            # Get the function spec so we can call it as a tool later.
            #
            # HTTP-based AsyncAgentSession implementations wrap any transport-level
            # or JSON-decoding error as a ValueError (see AsyncHttpServiceAgentSession.function),
            # and AsyncDirectAgentSession bypasses the network entirely -- so ValueError is
            # the only failure surface we need to translate into a user-facing hint.
            try:
                function_response: Dict[str, Any] = await session.function(request_dict)
                self.function_json = function_response.get("function")
            except ValueError as exception:
                message: str = (
                    f"Problem accessing external agent {self.agent_url}.\n"
                    """
The server (which could be your own localhost) is currently not serving up
an agent network by that name. Try these hints:
1. Check to see that you do not have a typo in your reference to the external agent
   in the calling hocon file.
2. If you have control over the server, check to see that the agent network your are trying
   to reach has an entry in the manifest.hocon file whose value is set to true.
3. Consider restarting the server, as perhaps a server does not continually look
   for changes to hocon files or manifest files during normal operation.
4. If you are new to calling external agent networks, know that:
    a. Simply referencing an agent within your own hocon file with a / prefix
       does not mean the server is serving that agent up separately.
    b. Every agent that is externally referenceable needs its own hocon file
       which must also have an entry in the manifest.hocon file for the server.
    c. There is one and only one "front man" agent note in each network described
       by a hocon file that receives input on behalf of the network.
    d. In order to be called by external agents, that front man must have a
       "function" definition which includes a description. Declaring at least
       one parameter is recommended, as parameters are how calling agents know
       what to pass; when none are declared, a single "inquiry" string parameter
       is synthesized on the calling side so the caller's request still gets through.
"""
                )
                raise ValueError(message) from exception

        return self.function_json
