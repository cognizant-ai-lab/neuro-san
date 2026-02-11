
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
"""
See class comment for details
"""

from typing import Any
from typing import Dict
from typing import List

import json
import random
import threading

import tornado

from neuro_san.internals.interfaces.agent_network_provider import AgentNetworkProvider
from neuro_san.internals.interfaces.agent_state_listener import AgentStateListener
from neuro_san.internals.interfaces.agent_storage_source import AgentStorageSource
from neuro_san.service.interfaces.startable import Startable
from neuro_san.internals.network_providers.agent_network_storage import AgentNetworkStorage
from neuro_san.service.generic.agent_server_logging import AgentServerLogging
from neuro_san.service.generic.async_agent_service_provider import AsyncAgentServiceProvider
from neuro_san.service.http.handlers.health_check_handler import HealthCheckHandler
from neuro_san.service.http.handlers.connectivity_handler import ConnectivityHandler
from neuro_san.service.http.handlers.function_handler import FunctionHandler
from neuro_san.service.http.handlers.streaming_chat_handler import StreamingChatHandler
from neuro_san.service.http.handlers.concierge_handler import ConciergeHandler
from neuro_san.service.http.handlers.openapi_publish_handler import OpenApiPublishHandler
from neuro_san.service.http.interfaces.agent_authorizer import AgentAuthorizer
from neuro_san.service.http.logging.http_logger import HttpLogger
from neuro_san.service.http.server.resources_usage_logger import ResourcesUsageLogger
from neuro_san.service.http.server.http_server_app import HttpServerApp
from neuro_san.service.interfaces.agent_server import AgentServer
from neuro_san.service.interfaces.event_loop_logger import EventLoopLogger
from neuro_san.service.utils.server_status import ServerStatus
from neuro_san.service.utils.server_context import ServerContext
from neuro_san.service.http.config.http_server_config import HttpServerConfig
from neuro_san.service.mcp.handlers.mcp_root_handler import McpRootHandler


DEFAULT_SERVER_NAME: str = 'neuro-san.Agent'
DEFAULT_SERVER_NAME_FOR_LOGS: str = 'Agent Server'
DEFAULT_MAX_CONCURRENT_REQUESTS: int = 10

# Better that we kill ourselves than kubernetes doing it for us
# in the middle of a request if there are resource leaks.
# This is per the lifetime of the server (before it kills itself).
DEFAULT_REQUEST_LIMIT: int = 1000 * 1000


class HttpServer(AgentAuthorizer, AgentStateListener):
    """
    Class provides simple http endpoint for neuro-san API.
    """
    # pylint: disable=too-many-instance-attributes
    # pylint: disable=too-many-arguments, too-many-positional-arguments

    TIMEOUT_TO_START_SECONDS: int = 10

    def __init__(self,
                 server_context: ServerContext,
                 server_config: HttpServerConfig,
                 openapi_service_spec_path: str,
                 requests_limit: int,
                 forwarded_request_metadata: str = AgentServer.DEFAULT_FORWARDED_REQUEST_METADATA):
        """
        Constructor:
        :param server_context: ServerContext with global-ish state
        :param server_config: http server run-time configuration
        :param openapi_service_spec_path: path to a file with OpenAPI service specification;
        :param requests_limit: The number of requests to service before shutting down.
                        This is useful to be sure production environments can handle
                        a service occasionally going down.
        :param forwarded_request_metadata: A space-delimited list of http metadata request keys
               to forward to logs/other requests
        """
        self.server_name_for_logs: str = "Http Server"
        self.server_config = server_config
        self.http_port = self.server_config.http_port
        self.server_context: ServerContext = server_context

        # Randomize requests limit for this server instance.
        # Lower and upper bounds for number of requests before shutting down
        if requests_limit == -1:
            # Unlimited requests
            self.requests_limit = -1
        else:
            request_limit_lower = round(requests_limit * 0.90)
            request_limit_upper = round(requests_limit * 1.10)
            self.requests_limit = random.randint(request_limit_lower, request_limit_upper)

        self.openapi_service_spec_path: str = openapi_service_spec_path
        self.forwarded_request_metadata: List[str] = forwarded_request_metadata.split(" ")
        self.logger = HttpLogger(self.forwarded_request_metadata)
        self.allowed_agents: Dict[str, AsyncAgentServiceProvider] = {}
        self.lock = threading.Lock()

        # Add listener to handle adding per-agent http service
        # (services map is defined by self.allowed_agents dictionary)
        network_storage_dict: Dict[str, AgentNetworkStorage] = self.server_context.get_network_storage_dict()
        for network_storage in network_storage_dict.values():
            network_storage.add_listener(self)

    def start(self, startables: List[Startable]):
        """
        Method to be called by a thread running tornado HTTP server
        to actually start serving requests.
        :param startables: List of Startable instances to start once server
            has forked its multiple running instances.
        """
        app = self.make_app(self.requests_limit, self.logger)

        self.logger.debug({}, "Serving agents: %s", repr(self.allowed_agents.keys()))

        # Create an HTTP server with run-time parameters
        server = tornado.httpserver.HTTPServer(
            app,
            idle_connection_timeout=self.server_config.http_idle_connection_timeout_seconds
        )

        if self.server_config.http_server_monitor_interval_seconds > 0:
            # Add resources usage logger to list of things we need to start
            # after http server is spun up:
            resources_logger: Startable =\
                ResourcesUsageLogger(
                    self.server_config.http_server_monitor_interval_seconds, self.http_port, self.logger)
            startables.append(resources_logger)

        # Bind the socket with a custom backlog
        server.bind(self.http_port, backlog=self.server_config.http_connections_backlog)

        # Start N child processes (0 = one per CPU core)
        server.start(self.server_config.http_server_instances)

        server_status: ServerStatus = self.server_context.get_server_status()
        server_status.http_service.set_status(True)
        self.logger.info({}, "HTTP server is running %d instances on port %d with backlog %d",
                         self.server_config.http_server_instances,
                         self.http_port,
                         self.server_config.http_connections_backlog)
        self.logger.info({}, "HTTP server idle connections timeout: %d seconds",
                         self.server_config.http_idle_connection_timeout_seconds)
        self.logger.info({}, "HTTP server is shutting down after %d requests", self.requests_limit)

        # If HTTP server is ready, our MCP server is also ready, if requested to run.
        if server_status.mcp_service.is_requested():
            server_status.mcp_service.set_status(True)
            mcp_version: str = self.server_context.get_mcp_server_context().get_protocol_version()
            self.logger.info({}, f"MCP server is running protocol {mcp_version}")

        if startables:
            for startable in startables:
                if isinstance(startable, Startable):
                    try:
                        startable.start()
                    except Exception as exception:  # pylint: disable=broad-exception-caught
                        self.logger.error(
                            {}, "Failed to start %s: %s",
                            startable.__class__.__name__, str(exception))

        tornado.ioloop.IOLoop.current().start()
        self.logger.info({}, "Http server stopped.")

    def make_app(self, requests_limit: int, logger: EventLoopLogger):
        """
        Construct tornado HTTP "application" to run.
        """
        # Do we need to enable HTTP request handlers?
        enable_http_handlers: bool = self.server_context.get_server_status().http_service.is_requested()

        request_initialize_data: Dict[str, Any] = self.build_request_data()
        live_request_initialize_data: Dict[str, Any] = {
            "forwarded_request_metadata": self.forwarded_request_metadata,
            "server_status": self.server_context.get_server_status(),
            "op": "live"
        }
        ready_request_initialize_data: Dict[str, Any] = {
            "forwarded_request_metadata": self.forwarded_request_metadata,
            "server_status": self.server_context.get_server_status(),
            "op": "ready"
        }
        handlers = []
        # Health check handlers are enabled always
        handlers.append(("/", HealthCheckHandler, ready_request_initialize_data))
        handlers.append(("/healthz", HealthCheckHandler, ready_request_initialize_data))
        handlers.append(("/readyz", HealthCheckHandler, ready_request_initialize_data))
        handlers.append(("/livez", HealthCheckHandler, live_request_initialize_data))

        if enable_http_handlers:
            handlers.append(("/api/v1/list", ConciergeHandler, request_initialize_data))
            handlers.append(("/api/v1/docs", OpenApiPublishHandler, request_initialize_data))

            # Register templated request paths for agent API methods:
            # regexp format used here is that of Python Re standard library.
            handlers.append((r"/api/v1/(.+)/function", FunctionHandler, request_initialize_data))
            handlers.append((r"/api/v1/(.+)/connectivity", ConnectivityHandler, request_initialize_data))
            handlers.append((r"/api/v1/(.+)/streaming_chat", StreamingChatHandler, request_initialize_data))

        # Register MCP "root" handler for all MCP requests
        # if MCP server is enabled:
        if self.server_context.get_mcp_server_context().is_enabled():
            handlers.append((r"/mcp", McpRootHandler, request_initialize_data))

        return HttpServerApp(handlers, requests_limit, logger, self.forwarded_request_metadata)

    def allow(self, agent_name) -> AsyncAgentServiceProvider:
        return self.allowed_agents.get(agent_name)

    def agent_added(self, agent_name: str, source: AgentStorageSource):
        """
        Add agent to the map of known agents
        :param agent_name: name of an agent
        :param source: The AgentStorageSource source of the message
        """
        agent_network_provider: AgentNetworkProvider = source.get_agent_network_provider(agent_name)

        # Convert back to a single string as required by constructor
        request_metadata_str: str = " ".join(self.forwarded_request_metadata)
        agent_server_logging: AgentServerLogging = \
            AgentServerLogging(self.server_name_for_logs, request_metadata_str)
        agent_service_provider: AsyncAgentServiceProvider = \
            AsyncAgentServiceProvider(
                self.logger,
                None,
                agent_name,
                agent_network_provider,
                agent_server_logging,
                self.server_context)
        self.allowed_agents[agent_name] = agent_service_provider
        self.logger.info({}, "Added agent %s to allowed http service list", agent_name)

    def agent_removed(self, agent_name: str, source: AgentStorageSource):
        """
        Remove agent from the map of known agents
        :param agent_name: name of an agent
        :param source: The AgentStorageSource source of the message
        """
        self.allowed_agents.pop(agent_name, None)
        self.logger.info({}, "Removed agent %s from allowed http service list", agent_name)

    def agent_modified(self, agent_name: str, source: AgentStorageSource):
        """
        Agent is being modified in the service scope.
        :param agent_name: name of an agent
        :param source: The AgentStorageSource source of the message
        """
        agent_service_provider: AsyncAgentServiceProvider = self.allowed_agents.get(agent_name, None)
        if agent_service_provider is not None:
            agent_service_provider.reset_service()
            self.logger.info({}, "Reset service for modified agent %s", agent_name)

    def build_request_data(self) -> Dict[str, Any]:
        """
        Build request data for Http handlers.
        :return: a dictionary with request data to be passed to an http handler.
        """
        open_api_dict: Dict[str, Any] = None
        try:
            with open(self.openapi_service_spec_path, "r", encoding='utf-8') as f_out:
                open_api_dict = json.load(f_out)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise ValueError(f"Failed to load '{self.openapi_service_spec_path}'") from exc

        return {
            "agent_policy": self,
            "forwarded_request_metadata": self.forwarded_request_metadata,
            "openapi_service_spec": open_api_dict,
            "server_context": self.server_context
        }
