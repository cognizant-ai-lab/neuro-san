
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
"""
See class comment for details
"""

from typing import Any
from typing import Dict
from typing import List

import random
import threading
import time

from tornado.ioloop import IOLoop

from neuro_san.internals.network_providers.agent_network_storage import AgentNetworkStorage
from neuro_san.internals.network_providers.single_agent_network_provider import SingleAgentNetworkProvider
from neuro_san.service.generic.agent_server_logging import AgentServerLogging
from neuro_san.service.generic.async_agent_service_provider import AsyncAgentServiceProvider
from neuro_san.service.http.handlers.health_check_handler import HealthCheckHandler
from neuro_san.service.http.handlers.connectivity_handler import ConnectivityHandler
from neuro_san.service.http.handlers.function_handler import FunctionHandler
from neuro_san.service.http.handlers.streaming_chat_handler import StreamingChatHandler
from neuro_san.service.http.handlers.concierge_handler import ConciergeHandler
from neuro_san.service.http.handlers.openapi_publish_handler import OpenApiPublishHandler
from neuro_san.service.http.interfaces.agent_authorizer import AgentAuthorizer
from neuro_san.service.http.interfaces.agents_updater import AgentsUpdater
from neuro_san.service.http.logging.http_logger import HttpLogger
from neuro_san.service.http.server.http_server_app import HttpServerApp
from neuro_san.service.interfaces.agent_server import AgentServer
from neuro_san.service.interfaces.event_loop_logger import EventLoopLogger


class HttpSidecar(AgentAuthorizer, AgentsUpdater):
    """
    Class provides simple http endpoint for neuro-san API.
    """
    # pylint: disable=too-many-instance-attributes
    # pylint: disable=too-many-arguments, too-many-positional-arguments

    TIMEOUT_TO_START_SECONDS: int = 10

    def __init__(self, start_event: threading.Event,
                 http_port: int,
                 openapi_service_spec_path: str,
                 requests_limit: int,
                 network_storage_dict: Dict[str, AgentNetworkStorage],
                 forwarded_request_metadata: str = AgentServer.DEFAULT_FORWARDED_REQUEST_METADATA):
        """
        Constructor:
        :param start_event: event to await before starting actual service;
        :param http_port: port for http neuro-san service;
        :param openapi_service_spec_path: path to a file with OpenAPI service specification;
        :param request_limit: The number of requests to service before shutting down.
                        This is useful to be sure production environments can handle
                        a service occasionally going down.
        :param network_storage_dict: A dictionary of string (descripting scope) to
                    AgentNetworkStorage instance which keeps all the AgentNetwork instances
                    of a particular grouping.
        :param forwarded_request_metadata: A space-delimited list of http metadata request keys
               to forward to logs/other requests
        """
        self.server_name_for_logs: str = "Http Server"
        self.start_event: threading.Event = start_event
        self.http_port = http_port
        self.network_storage_dict: Dict[str, AgentNetworkStorage] = network_storage_dict

        # Randomize requests limit for this server instance.
        # Lower and upper bounds for number of requests before shutting down
        if requests_limit == -1:
            # Unlimited requests
            self.requests_limit = -1
        else:
            request_limit_lower = round(requests_limit * 0.90)
            request_limit_upper = round(requests_limit * 1.10)
            self.requests_limit = random.randint(request_limit_lower, request_limit_upper)

        self.logger = None
        self.openapi_service_spec_path: str = openapi_service_spec_path
        self.forwarded_request_metadata: List[str] = forwarded_request_metadata.split(" ")
        self.allowed_agents: Dict[str, AsyncAgentServiceProvider] = {}
        self.allowed_last_modified: float = 0
        self.lock = None

    def __call__(self, other_server: AgentServer):
        """
        Method to be called by a thread running tornado HTTP server
        to actually start serving requests.
        """
        self.lock = threading.Lock()
        self.logger = HttpLogger(self.forwarded_request_metadata)
        app = self.make_app(self.requests_limit, self.logger)

        # Wait for "go" signal which will be set by higher-level machinery
        # when everything is ready for servicing.
        while not self.start_event.wait(timeout=self.TIMEOUT_TO_START_SECONDS):
            self.logger.error({},
                              "Timeout (%d sec) waiting for signal to HTTP server to start",
                              self.TIMEOUT_TO_START_SECONDS)

        # Construct initial "allowed" list of agents:
        # no metadata to use here yet.
        self.update_agents(metadata={})
        self.logger.debug({}, "Serving agents: %s", repr(self.allowed_agents.keys()))
        app.listen(self.http_port)
        self.logger.info({}, "HTTP server is running on port %d", self.http_port)
        self.logger.info({}, "HTTP server is shutting down after %d requests", self.requests_limit)

        IOLoop.current().start()
        self.logger.info({}, "Http server stopped.")
        if other_server is not None:
            other_server.stop()

    def make_app(self, requests_limit: int, logger: EventLoopLogger):
        """
        Construct tornado HTTP "application" to run.
        """
        request_data: Dict[str, Any] = self.build_request_data()
        health_request_data: Dict[str, Any] = {
            "forwarded_request_metadata": self.forwarded_request_metadata
        }
        handlers = []
        handlers.append(("/", HealthCheckHandler, health_request_data))
        handlers.append(("/healthz", HealthCheckHandler, health_request_data))
        handlers.append(("/api/v1/list", ConciergeHandler, request_data))
        handlers.append(("/api/v1/docs", OpenApiPublishHandler, request_data))

        # Register templated request paths for agent API methods:
        # regexp format used here is that of Python Re standard library.
        handlers.append((r"/api/v1/([^/]+)/function", FunctionHandler, request_data))
        handlers.append((r"/api/v1/([^/]+)/connectivity", ConnectivityHandler, request_data))
        handlers.append((r"/api/v1/([^/]+)/streaming_chat", StreamingChatHandler, request_data))

        return HttpServerApp(handlers, requests_limit, logger)

    def allow(self, agent_name) -> AsyncAgentServiceProvider:
        return self.allowed_agents.get(agent_name)

    def is_needing_allowed_update(self) -> bool:
        """
        Quick low-impact check to see if the allowed list of agents need updating.

        :return: True if the allowed_agents list needs updating. False otherwise
        """
        # Start by taking a snapshot of when we were last modified without the lock
        last_modified: float = self.allowed_last_modified

        for network_storage in self.network_storage_dict.values():
            if last_modified < network_storage.get_last_modified():
                # Something has changed since the last time we looked
                return True

        # Nothing has changed
        return False

    def update_agents(self, metadata: Dict[str, Any]):
        """
        Update list of agents for which serving is allowed.
        :param metadata: metadata to be used for logging if necessary.
        :return: nothing
        """
        _ = metadata

        # First do a quick check against network storage timestamps to see if
        # we need to anything more heavyweight.
        if not self.is_needing_allowed_update():
            return

        # Keep a list of the new allowed agents.
        new_allowed_names: List[str] = []
        for network_storage in self.network_storage_dict.values():
            # Add to the list of agents from the storage as the new allowed set.
            agent_names: List[str] = network_storage.get_agent_names()
            new_allowed_names.extend(agent_names)

        with self.lock:

            modified: bool = False

            # We assume all agents from "new_allowed_names" list are enabled:
            for agent_name in new_allowed_names:
                if self.allowed_agents.get(agent_name) is None:
                    self.add_agent(agent_name)
                    modified = True

            # All other agents are disabled:
            allowed_set = set(self.allowed_agents.keys())
            for agent_name in allowed_set:
                if agent_name not in new_allowed_names:
                    self.remove_agent(agent_name)
                    modified = True

            if modified:
                self.allowed_last_modified = time.time()

    def add_agent(self, agent_name: str):
        """
        Add agent to the map of known agents
        :param agent_name: name of an agent
        """
        public_storage: AgentNetworkStorage = self.network_storage_dict.get("public")
        agent_network_provider: SingleAgentNetworkProvider = \
            public_storage.get_agent_network_provider(agent_name)
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
                agent_server_logging)
        self.allowed_agents[agent_name] = agent_service_provider

    def remove_agent(self, agent_name: str):
        """
        Remove agent from the map of known agents
        :param agent_name: name of an agent
        """
        self.allowed_agents.pop(agent_name, None)

    def build_request_data(self) -> Dict[str, Any]:
        """
        Build request data for Http handlers.
        :return: a dictionary with request data to be passed to a http handler.
        """
        return {
            "agent_policy": self,
            "agents_updater": self,
            "forwarded_request_metadata": self.forwarded_request_metadata,
            "openapi_service_spec_path": self.openapi_service_spec_path,
            "network_storage_dict": self.network_storage_dict
        }
