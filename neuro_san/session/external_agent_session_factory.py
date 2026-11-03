
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
from asyncio import run_coroutine_threadsafe
from concurrent.futures import Future
from typing import Any
from typing import Coroutine
from typing import Dict
from typing import List
from urllib.parse import urlparse

from logging import getLogger
from logging import Logger

from typing_extensions import override

from leaf_common.asyncio.asyncio_executor import AsyncioExecutor
from leaf_common.logging.log_once import LogOnce
from leaf_common.utils.environment_util import EnvironmentUtil as Env

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
        executor: AsyncioExecutor = invocation_context.get_asyncio_executor()
        if executor.is_running_in_owned_loop():
            raise RuntimeError("create_session() cannot be called from the event loop of the invocation's "
                               "AsyncioExecutor. It will hang. Use async_create_session() instead")

        logger: Logger = getLogger(ExternalAgentSessionFactory.__name__)
        log_once: LogOnce = LogOnce(logger)
        log_once.info("create_session() is deprecated. Use async_create_session() instead.")

        coroutine: Coroutine[Any, Any, AsyncAgentSession] = self.async_create_session(
            agent_url,
            invocation_context,
            invocation)
        # Run the coroutine on the event loop of the invocation's AsyncioExecutor
        # and block this thread until it completes.
        # Sessions bind to an event loop lazily, when a request is first made, so the
        # returned session is still usable on the caller's loop.
        future: Future = run_coroutine_threadsafe(coroutine, executor.get_event_loop())
        session: AsyncAgentSession = future.result()
        return session

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

        # Fetched storage is keyed by the full URL, so create_fetched_session() consults it instead.
        storage_name: str = None
        for storage_name in storage_source_dict.keys():
            if storage_name not in (StorageClass.TEMP, StorageClass.FETCHED):
                networks_order.append(storage_name)

        if StorageClass.TEMP in storage_source_dict.keys():
            networks_order.append(StorageClass.TEMP)

        return networks_order

    async def create_session_from_location_dict(self, agent_location: Dict[str, str],
                                                invocation_context: InvocationContext,
                                                invocation: str = None) -> AsyncAgentSession:
        """
        Creates the session for an external agent from its parsed location, in-process when possible.

        With use_direct, a local agent network is tried first, then an agent network
        file fetched from the full "agent_url". An http session is the last resort,
        as its creation does not check that the agent is reachable.

        :param agent_location: An agent location dictionary returned by
                    ExternalAgentParsing.parse_external_agent().
                    When its "scheme" is "https", the http session built here
                    talks https; any other (or absent) scheme talks plain http.
                    Without an "agent_url" key, no agent network file is fetched.
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
            session = await self.create_local_session(agent_name, invocation_context, invocation, metadata)

        agent_url: str = agent_location.get("agent_url")
        if session is None and agent_url is not None:
            # The fetched storage is keyed by the full URL, not by the parsed agent name.
            session = await self.create_fetched_session(agent_url, invocation_context, invocation)

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

    async def create_local_session(self, agent_name: str,
                                   invocation_context: InvocationContext,
                                   invocation: str,
                                   metadata: Dict[str, str]) -> AsyncAgentSession:
        """
        Creates a direct session for an agent network found in the storages of this process.

        :param agent_name: The name of the agent network, as parsed from its reference
        :param invocation_context: The context policy container that pertains to the invocation
                    of the agent.
        :param invocation: String describing how the agent wants to be invoked.
        :param metadata: The request metadata to forward to the session
        :return: An AsyncAgentSession for the agent network, or None when no storage has it
        """
        # Optimization: We want to create a different kind of session to minimize socket usage
        # and potentially relieve the direct user of the burden of having to start a server

        # Stop at the first storage that has the agent network
        agent_network_provider: AgentNetworkProvider = None
        storage_source_name: str = None
        for storage_source_name in self.get_networks_order(self.storage_source_dict):

            storage_source: AgentStorageSource = self.storage_source_dict.get(storage_source_name)
            # Be sure we have something
            agent_network_provider = await storage_source.async_get_agent_network_provider(agent_name)
            if agent_network_provider is None:
                continue

            if agent_network_provider.get_agent_network() is not None:
                break

        if agent_network_provider is None:
            return None

        agent_network: AgentNetwork = agent_network_provider.get_agent_network()
        if agent_network is None:
            return None

        safe_invocation_context: SessionInvocationContext = invocation_context.safe_shallow_copy(invocation)
        session: AsyncAgentSession = AsyncDirectAgentSession(agent_network, safe_invocation_context,
                                                             metadata=metadata)
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

    async def create_fetched_session(self, agent_url: str,
                                     invocation_context: InvocationContext,
                                     invocation: str = None) -> AsyncAgentSession:
        """
        Creates a direct session for an agent network whose spec is fetched from the given URL.

        :param agent_url: An url string pointing to an agent network file
        :param invocation_context: The context policy container that pertains to the invocation
                    of the agent.
        :param invocation: String describing how the agent wants to be invoked.
        :return: An AsyncAgentSession for the fetched agent network, or None when
                 there is no fetched storage, the URL is plain http while
                 AGENT_SESSION_REQUIRE_HTTPS is true, or the URL does not yield an agent network.
        """
        if not self.is_use_direct() or self.storage_source_dict is None:
            return None

        # Same default and parsing as AbstractHttpServiceAgentSession.get_request_path():
        # permissive unless a server opts in.
        require_https: bool = Env.getenv("AGENT_SESSION_REQUIRE_HTTPS", "false").lower() == "true"
        scheme: str = urlparse(agent_url).scheme
        lower_scheme: str = scheme.lower()
        if require_https and lower_scheme == "http":
            logger: Logger = getLogger(ExternalAgentSessionFactory.__name__)
            logger.warning("AGENT_SESSION_REQUIRE_HTTPS=true forbids fetching %s over plain http", agent_url)
            return None

        fetched_storage: AgentStorageSource = self.storage_source_dict.get(StorageClass.FETCHED)
        if fetched_storage is None:
            return None

        agent_network_provider: AgentNetworkProvider = \
            await fetched_storage.async_get_agent_network_provider(agent_url)
        if agent_network_provider is None:
            return None

        agent_network: AgentNetwork = agent_network_provider.get_agent_network()
        if agent_network is None:
            return None

        metadata: Dict[str, str] = invocation_context.get_metadata()
        safe_invocation_context: SessionInvocationContext = invocation_context.safe_shallow_copy(invocation)
        session: AsyncAgentSession = AsyncDirectAgentSession(agent_network, safe_invocation_context,
                                                             metadata=metadata)
        return session
