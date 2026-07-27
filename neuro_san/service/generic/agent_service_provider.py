
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

from copy import deepcopy
from threading import Lock

from leaf_server_common.server.request_logger import RequestLogger

from neuro_san.internals.interfaces.agent_network_provider import AgentNetworkProvider
from neuro_san.service.generic.agent_service import AgentService
from neuro_san.service.generic.agent_server_logging import AgentServerLogging
from neuro_san.service.interfaces.server_context_lite import ServerContextLite


# pylint: disable=too-many-instance-attributes
class AgentServiceProvider:
    """
    Class providing lazy construction of AgentService instance
    with given constructor parameters.
    """

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def __init__(self,
                 request_logger: RequestLogger,
                 security_cfg: Dict[str, Any],
                 agent_name: str,
                 agent_network_provider: AgentNetworkProvider,
                 server_logging: AgentServerLogging,
                 server_context: ServerContextLite):
        """
        Constructor.
        :param request_logger: The instance of the RequestLogger that helps
                    keep track of stats
        :param security_cfg: A dictionary of parameters used to
                        secure the TLS and the authentication of the gRPC
                        connection.  Supplying this implies use of a secure
                        GRPC Channel.  If None, uses insecure channel.
        :param agent_name: The agent name for the service
        :param agent_network_provider: The AgentNetworkProvider to use for the session.
        :param server_logging: An AgentServerLogging instance initialized so that
                        spawned asynchronous threads can also properly initialize
                        their logging.
        :param server_context: The ServerContext object with global-ish state
        """
        self.request_logger = request_logger
        self.security_cfg = deepcopy(security_cfg)
        self.server_logging: AgentServerLogging = server_logging
        self.agent_network_provider: AgentNetworkProvider = agent_network_provider
        self.agent_name: str = agent_name
        self.lock: Lock = Lock()
        self.server_context: ServerContextLite = server_context
        self.service_instance: AgentService = None

    def get_service(self) -> AgentService:
        """
        Get service instance.
        Create it if it is not instantiated yet.
        """
        if self.service_instance is None:
            with self.lock:
                if self.service_instance is None:
                    self.service_instance = AgentService(
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
