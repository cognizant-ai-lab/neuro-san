
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

from typing import Dict
from typing import List
import threading

import logging

from leaf_server_common.server.server_lifetime import ServerLifetime
from leaf_server_common.server.server_loop_callbacks import ServerLoopCallbacks

from neuro_san.api.grpc import agent_pb2
from neuro_san.api.grpc import concierge_pb2_grpc

from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.network_providers.service_agent_network_storage import ServiceAgentNetworkStorage
from neuro_san.service.grpc.agent_servicer_to_server import AgentServicerToServer
from neuro_san.service.grpc.concierge_service import ConciergeService
from neuro_san.service.grpc.dynamic_agent_router import DynamicAgentRouter
from neuro_san.service.grpc.grpc_agent_service import GrpcAgentService
from neuro_san.service.logging.agent_server_logging import AgentServerLogging
from neuro_san.session.agent_service_stub import AgentServiceStub

DEFAULT_SERVER_NAME: str = 'neuro-san.Agent'
DEFAULT_SERVER_NAME_FOR_LOGS: str = 'Agent Server'
DEFAULT_MAX_CONCURRENT_REQUESTS: int = 10

# Better that we kill ourselves than kubernetes doing it for us
# in the middle of a request if there are resource leaks.
# This is per the lifetime of the server (before it kills itself).
DEFAULT_REQUEST_LIMIT: int = 1000 * 1000

# A space-delimited list of http metadata request keys to forward to logs/other requests
DEFAULT_FORWARDED_REQUEST_METADATA: str = "request_id user_id"


# pylint: disable=too-many-instance-attributes
class AgentServer:
    """
    Server implementation for the Agent gRPC Service.
    """

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def __init__(self, port: int,
                 server_loop_callbacks: ServerLoopCallbacks,
                 agent_networks: Dict[str, AgentNetwork],
                 server_name: str = DEFAULT_SERVER_NAME,
                 server_name_for_logs: str = DEFAULT_SERVER_NAME_FOR_LOGS,
                 max_concurrent_requests: int = DEFAULT_MAX_CONCURRENT_REQUESTS,
                 request_limit: int = DEFAULT_REQUEST_LIMIT,
                 forwarded_request_metadata: str = DEFAULT_FORWARDED_REQUEST_METADATA):
        """
        Constructor

        :param port: The integer port number for the service to listen on
        :param server_loop_callbacks: The ServerLoopCallbacks instance for
                break out methods in main serving loop.
        :param agent_networks: A dictionary of agent name to AgentNetwork to use for the session.
        :param server_name: The name of the service
        :param server_name_for_logs: The name of the service for log files
        :param max_concurrent_requests: The maximum number of requests to handle at a time.
        :param request_limit: The number of requests to service before shutting down.
                        This is useful to be sure production environments can handle
                        a service occasionally going down.
        :param forwarded_request_metadata: A space-delimited list of http metadata request keys
                        to forward to logs/other requests
        """
        self.port = port
        self.server_loop_callbacks = server_loop_callbacks

        self.server_logging = AgentServerLogging(server_name_for_logs, forwarded_request_metadata)
        self.server_logging.setup_logging()

        self.logger = logging.getLogger(__name__)

        self.agent_networks: Dict[str, AgentNetwork] = agent_networks
        self.server_name: str = server_name
        self.server_name_for_logs: str = server_name_for_logs
        self.max_concurrent_requests: int = max_concurrent_requests
        self.request_limit: int = request_limit

        self.server_lifetime = None
        self.security_cfg = None
        self.services: List[GrpcAgentService] = []
        self.service_router: DynamicAgentRouter = DynamicAgentRouter()
        # Event to notify that we have started serving
        self.notify_started: threading.Event = threading.Event()
        self.logger.info("agent_networks found: %s", str(list(self.agent_networks.keys())))

    def get_services(self) -> List[GrpcAgentService]:
        """
        :return: A list of the AgentServices being served up by this instance
        """
        return self.services

    def get_starting_event(self) -> threading.Event:
        """
        Get event signalling that server has started work.
        """
        return self.notify_started

    def setup_agent_network_storage(self):
        """
        Initialize ServiceAgentNetworkStorage with AgentNetworks
        we have parsed in server manifest file.
        """
        network_storage: ServiceAgentNetworkStorage =\
            ServiceAgentNetworkStorage.get_instance()
        network_storage.setup_agent_networks(self.agent_networks)

    def agent_added(self, agent_name: str):
        """
        Agent is being added to the service.
        :param agent_name: name of an agent
        """
        network_storage: ServiceAgentNetworkStorage =\
            ServiceAgentNetworkStorage.get_instance()
        service = GrpcAgentService(self.server_lifetime, self.security_cfg,
                                   agent_name,
                                   network_storage.get_agent_network_provider(agent_name),
                                   self.server_logging)
        self.services.append(service)
        servicer_to_server = AgentServicerToServer(service)
        agent_rpc_handlers = servicer_to_server.build_rpc_handlers()
        agent_service_name: str = AgentServiceStub.prepare_service_name(agent_name)
        self.service_router.add_service(agent_service_name, agent_rpc_handlers)

    def agent_modified(self, agent_name: str):
        """
        Agent is being modified in the service scope.
        :param agent_name: name of an agent
        """
        # Endpoints configuration has not changed,
        # so nothing to do here, actually.
        _ = agent_name

    def agent_removed(self, agent_name: str):
        """
        Agent is being removed from the service.
        :param agent_name: name of an agent
        """
        agent_service_name: str = AgentServiceStub.prepare_service_name(agent_name)
        self.service_router.remove_service(agent_service_name)

    def serve(self):
        """
        Start serving gRPC requests
        """
        values = agent_pb2.DESCRIPTOR.services_by_name.values()
        self.server_lifetime = ServerLifetime(
            self.server_name,
            self.server_name_for_logs,
            self.port, self.logger,
            request_limit=self.request_limit,
            max_workers=self.max_concurrent_requests,
            max_concurrent_rpcs=None,
            # Used for health checking. Probably needs agent-specific love.
            protocol_services_by_name_values=values,
            loop_sleep_seconds=5.0,
            server_loop_callbacks=self.server_loop_callbacks)

        server = self.server_lifetime.create_server()

        # New-style service
        self.security_cfg = None     # ... yet

        network_storage: ServiceAgentNetworkStorage = \
            ServiceAgentNetworkStorage.get_instance()
        # Add listener to handle adding per-agent gRPC services
        # to our dynamic router:
        network_storage.add_listener(self)

        self.setup_agent_network_storage()

        # Add DynamicAgentRouter instance as a generic RPC handler for our server:
        server.add_generic_rpc_handlers((self.service_router,))

        concierge_service: ConciergeService = \
            ConciergeService(self.server_lifetime,
                             self.security_cfg,
                             self.server_logging)
        concierge_pb2_grpc.add_ConciergeServiceServicer_to_server(
            concierge_service,
            server)

        self.notify_started.set()
        self.server_lifetime.run()

    def stop(self):
        """
        Stop the server.
        """
        # pylint: disable=protected-access
        self.server_lifetime._stop_serving()
