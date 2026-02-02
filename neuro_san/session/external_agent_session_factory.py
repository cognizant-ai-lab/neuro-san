
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
from typing import Dict

from neuro_san.interfaces.async_agent_session import AsyncAgentSession
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.interfaces.async_agent_session_factory import AsyncAgentSessionFactory
from neuro_san.internals.interfaces.agent_network_provider import AgentNetworkProvider
from neuro_san.internals.interfaces.invocation_context import InvocationContext
from neuro_san.internals.run_context.utils.external_agent_parsing import ExternalAgentParsing
from neuro_san.internals.network_providers.agent_network_storage import AgentNetworkStorage
from neuro_san.session.async_direct_agent_session import AsyncDirectAgentSession
from neuro_san.session.async_http_service_agent_session import AsyncHttpServiceAgentSession


class ExternalAgentSessionFactory(AsyncAgentSessionFactory):
    """
    Creates AgentSessions for external agents.
    """

    def __init__(self, use_direct: bool = False,
                 network_storage_dict: Dict[str, AgentNetworkStorage] = None):
        """
        Constructor

        :param use_direct: When True, will use a Direct session for
                    external agents that would reside on the same server.
        :param network_storage_dict: A dictionary of AgentNetworkStorage instances which keeps all
                                the AgentNetwork instances.  Only used with use_direct=True.
        """
        self.use_direct: bool = use_direct
        self.network_storage_dict: Dict[str, AgentNetworkStorage] = None
        if self.use_direct:
            # Only store the reference if we will need it
            self.network_storage_dict = network_storage_dict

    def create_session(self, agent_url: str,
                       invocation_context: InvocationContext) -> AsyncAgentSession:
        """
        :param agent_url: An url string pointing to an external agent that came from
                    a tools list in an agent spec.
        :param invocation_context: The context policy container that pertains to the invocation
                    of the agent.
        :return: An AsyncAgentSession through which communications about the external agent can be made.
        """

        server_port: int = invocation_context.get_port()
        agent_location: Dict[str, str] = ExternalAgentParsing.parse_external_agent(agent_url, server_port=server_port)
        session: AsyncAgentSession = self.create_session_from_location_dict(agent_location, invocation_context)
        return session

    def create_session_from_location_dict(self, agent_location: Dict[str, str],
                                          invocation_context: InvocationContext) -> AsyncAgentSession:
        """
        :param agent_location: An agent location dictionary returned by
                    ExternalAgentParsing.parse_external_agent()
        :param invocation_context: The context policy container that pertains to the invocation
                    of the agent.
        :return: An AsyncAgentSession through which communications about the external agent can be made.
        """
        if agent_location is None:
            return None
        # Create the session.
        host = agent_location.get("host")
        port = agent_location.get("port")
        agent_name = agent_location.get("agent_name")

        # Note: It's possible we might want some filtering/translation of
        #       metadata keys not unlike what we are doing for sly_data.
        metadata: Dict[str, str] = None
        if invocation_context is not None:
            metadata = invocation_context.get_metadata()

        session: AsyncAgentSession = None
        if self.use_direct and (host is None or len(host) == 0 or host == "localhost"):

            # Optimization: We want to create a different kind of session to minimize socket usage
            # and potentially relieve the direct user of the burden of having to start a server

            agent_network_provider: AgentNetworkProvider = None
            for network_storage in self.network_storage_dict.values():
                # Be sure we have something
                agent_network_provider = network_storage.get_agent_network_provider(agent_name)
                if agent_network_provider.get_agent_network() is not None:
                    break

            agent_network: AgentNetwork = agent_network_provider.get_agent_network()
            safe_invocation_context: InvocationContext = invocation_context.safe_shallow_copy()
            session = AsyncDirectAgentSession(agent_network, safe_invocation_context, metadata=metadata)

        if session is None:
            # When creating a session for external agents, specifically use None for the
            # streaming timeout.  This implies an infinite amount of time to let the
            # external agent get its job done.  The rationale here is that:
            #   a)  We do not know how long any given external agent is really going to take
            #       to do its job.
            #   b)  We figure that the regular connection aspects to the server in question
            #       have already been sorted out in the obligitory call to function() that
            #       precedes any streaming_chat() call.
            session = AsyncHttpServiceAgentSession(host, port, agent_name=agent_name,
                                                   metadata=metadata, streaming_timeout_in_seconds=None)

        return session

    def is_use_direct(self) -> bool:
        """
        :return: When True, will use a Direct session for external agents that would reside on the same server.
        """
        return self.use_direct
