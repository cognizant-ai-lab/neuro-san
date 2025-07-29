
# Copyright (C) 2023-2025 Cognizant Digital Business, Evolutionary AI.
# All Rights Reserved.
# Issued under the Academic Public License.
#
# You can be released from the terms, and requirements of the Academic Public
# License by purchasing a commercial license.
# Purchase of a commercial license is mandatory for any use of the
# neuro-san SDK Software in commercial settings.
#
# END COPYRIGHT

from typing import Any
from typing import Dict
from threading import Lock
import copy

from neuro_san.internals.interfaces.agent_network_provider import AgentNetworkProvider
from neuro_san.service.interfaces.event_loop_logger import EventLoopLogger
from neuro_san.service.generic.async_agent_service import AsyncAgentService
from neuro_san.service.generic.agent_server_logging import AgentServerLogging
from neuro_san.service.utils.server_context import ServerContext


# pylint: disable=too-many-instance-attributes
class AsyncAgentServiceProvider:
    """
    Class providing lazy construction of AsyncAgentService instance
    with given constructor parameters.
    """

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def __init__(self,
                 request_logger: EventLoopLogger,
                 security_cfg: Dict[str, Any],
                 agent_name: str,
                 agent_network_provider: AgentNetworkProvider,
                 server_logging: AgentServerLogging,
                 server_context: ServerContext):
        """
        Constructor.
        :param request_logger: The instance of the EventLoopLogger that helps
                        log information from running event loop
        :param security_cfg: A dictionary of parameters used to
                        secure the TLS and the authentication of the gRPC
                        connection.  Supplying this implies use of a secure
                        GRPC Channel.  If None, uses insecure channel.
        :param agent_name: The agent name for the service
        :param agent_network_provider: The AgentNetworkProvider to use for the session.
        :param server_logging: An AgentServerLogging instance initialized so that
                        spawned asynchronous threads can also properly initialize
                        their logging.
        :param server_context: The ServerContext object containing global-ish state
        """
        self.request_logger = request_logger
        self.security_cfg = copy.deepcopy(security_cfg)
        self.server_logging: AgentServerLogging = server_logging
        self.agent_network_provider: AgentNetworkProvider = agent_network_provider
        self.agent_name: str = agent_name
        self.lock: Lock = Lock()
        self.server_context: ServerContext = server_context
        self.service_instance: AsyncAgentService = None

    def get_service(self) -> AsyncAgentService:
        """
        Get service instance.
        Create it if it is not instantiated yet.
        """
        if self.service_instance is None:
            with self.lock:
                if self.service_instance is None:
                    self.service_instance = AsyncAgentService(
                        self.request_logger,
                        self.security_cfg,
                        self.agent_name,
                        self.agent_network_provider,
                        self.server_logging,
                        self.server_context)
        return self.service_instance

    def service_created(self) -> bool:
        """
        Return True if service instance has already been instantiated;
               False otherwise
        """
        return self.service_instance is not None
