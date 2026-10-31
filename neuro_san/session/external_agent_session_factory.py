
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
from asyncio import get_running_loop
from asyncio import run
from concurrent.futures import Future
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from typing import Coroutine
from typing import Dict
from typing import List

from typing_extensions import override

from neuro_san.interfaces.async_agent_session import AsyncAgentSession
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.interfaces.agent_network_provider import AgentNetworkProvider
from neuro_san.internals.interfaces.async_agent_session_factory import AsyncAgentSessionFactory
from neuro_san.internals.interfaces.invocation_context import InvocationContext
from neuro_san.internals.interfaces.storage_class import StorageClass
from neuro_san.internals.interfaces.agent_storage_source import AgentStorageSource
from neuro_san.internals.utils.external_agent_parsing import ExternalAgentParsing
from neuro_san.session.async_direct_agent_session import AsyncDirectAgentSession
from neuro_san.session.async_http_service_agent_session import AsyncHttpServiceAgentSession
from neuro_san.session.session_invocation_context import SessionInvocationContext


class ExternalAgentSessionFactory(AsyncAgentSessionFactory):
    """
    Creates AgentSessions for external agents.
    """

    def __init__(self, use_direct: bool = False,
                 network_storage_dict: Dict[str, AgentStorageSource] = None):
        """
        Constructor

        :param use_direct: When True, will use a Direct session for
                    external agents that would reside on the same server.
        :param network_storage_dict: A dictionary of AgentStorageSource instances which keeps all
                                the AgentNetwork instances.  Only used with use_direct=True.
        """
        self.use_direct: bool = use_direct
        self.storage_source_dict: Dict[str, AgentStorageSource] = None
        if self.use_direct:
            # Only store the reference if we will need it
            self.storage_source_dict = network_storage_dict

    @override
    def create_session(self, agent_url: str,
                       invocation_context: InvocationContext,
                       invocation: str = None) -> AsyncAgentSession:
        """
        Synchronous version of async_create_session(), kept for backwards
        compatibility with external clients. Code within neuro-san calls
        async_create_session() instead.

        :param agent_url: An url string pointing to an external agent that came from
                    a tools list in an agent spec.
        :param invocation_context: The context policy container that pertains to the invocation
                    of the agent.
        :param invocation: String describing how the agent wants to be invoked.
                            Can be: "chatbot" - implies waiting for an answer.
                                    "event" - implies no answer needed
                                    None - implies chatbot
        :return: An AsyncAgentSession through which communications about the external agent can be made.
        """
        coroutine: Coroutine[Any, Any, AsyncAgentSession] = self.async_create_session(
            agent_url,
            invocation_context,
            invocation)
        try:
            get_running_loop()
        except RuntimeError:
            # No event loop is running in this thread, so run one here.
            return run(coroutine)

        # An event loop is already running in this thread. Waiting on it here would deadlock,
        # so run the coroutine on a fresh event loop in a worker thread and wait for that.
        # Sessions bind to an event loop lazily, when a request is first made, so the
        # returned session is still usable on the caller's loop.
        with ThreadPoolExecutor(max_workers=1) as executor:
            future: Future = executor.submit(run, coroutine)
            return future.result()

    async def async_create_session(self, agent_url: str,
                                   invocation_context: InvocationContext,
                                   invocation: str = None) -> AsyncAgentSession:
        """
        :param agent_url: An url string pointing to an external agent that came from
                    a tools list in an agent spec.
        :param invocation_context: The context policy container that pertains to the invocation
                    of the agent.
        :param invocation: String describing how the agent wants to be invoked.
                            Can be: "chatbot" - implies waiting for an answer.
                                    "event" - implies no answer needed
                                    None - implies chatbot
        :return: An AsyncAgentSession through which communications about the external agent can be made.
        """

        server_port: int = invocation_context.get_port()
        agent_location: Dict[str, str] = ExternalAgentParsing.parse_external_agent(agent_url, server_port=server_port)
        session: AsyncAgentSession = await self.create_session_from_location_dict(agent_location,
                                                                                  invocation_context,
                                                                                  invocation)
        return session

    def get_networks_order(self, storage_source_dict: Dict[str, AgentStorageSource]) -> List[str]:
        """
        :param storage_source_dict: The dictionary of AgentStorageSource instances to check for networks.
        :return: A List of AgentStorageSource names in the order they should be checked.
        Note: we need our "temp" storage to be checked last,
        because in the general case this might involve querying external storage, which is potentially slow.
        """
        networks_order: List[str] = []
        if storage_source_dict is None:
            return networks_order

        for storage_name in storage_source_dict.keys():
            if storage_name != StorageClass.TEMP:
                networks_order.append(storage_name)

        if StorageClass.TEMP in storage_source_dict.keys():
            networks_order.append(StorageClass.TEMP)

        return networks_order

    async def create_session_from_location_dict(self, agent_location: Dict[str, str],
                                                invocation_context: InvocationContext,
                                                invocation: str = None) -> AsyncAgentSession:
        """
        Creates the session for an external agent from its parsed location, in-process when possible.

        :param agent_location: An agent location dictionary returned by
                    ExternalAgentParsing.parse_external_agent().
                    When its "scheme" is "https", the http session built here
                    talks https; any other (or absent) scheme talks plain http.
        :param invocation_context: The context policy container that pertains to the invocation
                    of the agent.
        :param invocation: String describing how the agent wants to be invoked.
                            Can be: "chatbot" - implies waiting for an answer.
                                    "event" - implies no answer needed
                                    None - implies chatbot
        :return: An AsyncAgentSession through which communications about the external agent can be made.
        """
        if agent_location is None:
            return None

        # Create the session.
        host: str = agent_location.get("host")
        port: str = agent_location.get("port")
        agent_name: str = agent_location.get("agent_name")

        # Note: It's possible we might want some filtering/translation of
        #       metadata keys not unlike what we are doing for sly_data.
        metadata: Dict[str, str] = None
        if invocation_context is not None:
            metadata = invocation_context.get_metadata()

        session: AsyncAgentSession = None
        if self.is_use_direct() and (host is None or len(host) == 0 or host == "localhost"):

            # Optimization: We want to create a different kind of session to minimize socket usage
            # and potentially relieve the direct user of the burden of having to start a server

            agent_network_provider: AgentNetworkProvider = None
            for storage_source_name in self.get_networks_order(self.storage_source_dict):

                storage_source: AgentStorageSource = self.storage_source_dict.get(storage_source_name)
                # Be sure we have something
                agent_network_provider = await storage_source.async_get_agent_network_provider(agent_name)
                if agent_network_provider is None:
                    continue

                if agent_network_provider.get_agent_network() is not None:
                    break

            if agent_network_provider is not None:
                agent_network: AgentNetwork = agent_network_provider.get_agent_network()
                if agent_network is not None:
                    safe_invocation_context: SessionInvocationContext = invocation_context.safe_shallow_copy(invocation)
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
            security_cfg: Dict[str, Any] = self.get_security_cfg(agent_location)
            session = AsyncHttpServiceAgentSession(host, port, agent_name=agent_name,
                                                   metadata=metadata, security_cfg=security_cfg,
                                                   streaming_timeout_in_seconds=None)

        return session

    @staticmethod
    def get_security_cfg(agent_location: Dict[str, str]) -> Dict[str, Any]:
        """
        Derives the security_cfg for an http session from the scheme of the
        parsed external agent reference.

        :param agent_location: An agent location dictionary returned by
                    ExternalAgentParsing.parse_external_agent()
        :return: An empty dict when the reference used the https scheme, so that
                AbstractHttpServiceAgentSession.get_request_path() builds an
                https url. None otherwise, which keeps plain http.
        """
        # Dicts built by older callers may predate the "scheme" key.
        # Treat those as plain http, which is what they always got.
        scheme: str = agent_location.get("scheme", "")

        security_cfg: Dict[str, Any] = None
        if scheme == "https":
            # get_request_path() only checks security_cfg for being non-None
            # to pick the https scheme; the dict contents are not consulted.
            # An empty dict is the same "for now, to get the https scheme"
            # convention neuro_san/client/agent_session_factory.py uses.
            security_cfg = {}
        return security_cfg

    def is_use_direct(self) -> bool:
        """
        :return: When True, will use a Direct session for external agents that would reside on the same server.
        """
        return self.use_direct
