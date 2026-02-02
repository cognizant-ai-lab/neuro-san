
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
from typing import List

import os

from argparse import ArgumentParser

from leaf_server_common.logging.logging_setup import setup_logging

from neuro_san import DEPLOY_DIR
from neuro_san import TOP_LEVEL_DIR
from neuro_san.interfaces.agent_session import AgentSession
from neuro_san.service.interfaces.startable import Startable
from neuro_san.internals.graph.persistence.registry_manifest_restorer import RegistryManifestRestorer
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.network_providers.agent_network_storage import AgentNetworkStorage
from neuro_san.service.http.server.http_server import DEFAULT_SERVER_NAME
from neuro_san.service.http.server.http_server import DEFAULT_SERVER_NAME_FOR_LOGS
from neuro_san.service.http.server.http_server import DEFAULT_MAX_CONCURRENT_REQUESTS
from neuro_san.service.http.server.http_server import DEFAULT_REQUEST_LIMIT
from neuro_san.service.http.config.http_server_config import DEFAULT_HTTP_CONNECTIONS_BACKLOG
from neuro_san.service.http.config.http_server_config import DEFAULT_HTTP_IDLE_CONNECTIONS_TIMEOUT_SECONDS
from neuro_san.service.http.config.http_server_config import DEFAULT_HTTP_SERVER_INSTANCES
from neuro_san.service.http.config.http_server_config import DEFAULT_HTTP_SERVER_MONITOR_INTERVAL_SECONDS
from neuro_san.service.http.config.http_server_config import HttpServerConfig
from neuro_san.service.interfaces.agent_server import AgentServer
from neuro_san.service.http.server.http_server import HttpServer
from neuro_san.service.watcher.main_loop.storage_watcher import StorageWatcher
from neuro_san.service.utils.server_status import ServerStatus
from neuro_san.service.utils.server_context import ServerContext


# pylint: disable=too-many-instance-attributes
class ServerMainLoop:
    """
    This class handles the service main loop.
    """

    def __init__(self):
        """
        Constructor
        """
        self.http_port: int = 0

        self.agent_networks: Dict[str, Dict[str, AgentNetwork]] = {}

        self.server_name: str = DEFAULT_SERVER_NAME
        self.server_name_for_logs: str = DEFAULT_SERVER_NAME_FOR_LOGS
        self.max_concurrent_requests: int = DEFAULT_MAX_CONCURRENT_REQUESTS
        self.request_limit: int = DEFAULT_REQUEST_LIMIT
        self.forwarded_request_metadata: str = AgentServer.DEFAULT_FORWARDED_REQUEST_METADATA
        self.usage_logger_metadata: str = ""
        self.service_openapi_spec_file: str = self._get_default_openapi_spec_path()
        self.http_server: HttpServer = None
        self.server_context = ServerContext()
        self.http_server_config = HttpServerConfig()
        self.watcher_config: Dict[str, Any] = {}

    def prepare_args(self) -> ArgumentParser:
        """
        :return: An ArgumentParser set up to parse command-line arguments
        """
        # Set up the CLI parser
        arg_parser = ArgumentParser()

        # AGENT_PORT is a fallback for AGENT_HTTP_PORT for backward compatibility
        default_http_port = os.environ.get("AGENT_HTTP_PORT",
                                           os.environ.get("AGENT_PORT", AgentSession.DEFAULT_HTTP_PORT))
        arg_parser.add_argument("--http_port", type=int,
                                default=int(default_http_port),
                                help="Port number for http service endpoint")
        arg_parser.add_argument("--server_name", type=str,
                                default=str(os.environ.get("AGENT_SERVER_NAME", self.server_name)),
                                help="Name of the service for health reporting purposes.")
        arg_parser.add_argument("--server_name_for_logs", type=str,
                                default=str(os.environ.get("AGENT_SERVER_NAME_FOR_LOGS", self.server_name_for_logs)),
                                help="Name of the service as seen in logs")
        arg_parser.add_argument("--max_concurrent_requests", type=int,
                                default=int(os.environ.get("AGENT_MAX_CONCURRENT_REQUESTS",
                                                           self.max_concurrent_requests)),
                                help="Maximum number of requests that can be served at the same time")
        arg_parser.add_argument("--request_limit", type=int,
                                default=int(os.environ.get("AGENT_REQUEST_LIMIT", self.request_limit)),
                                help="Number of requests served before the server shuts down in an orderly fashion")
        arg_parser.add_argument("--forwarded_request_metadata", type=str,
                                default=os.environ.get("AGENT_FORWARDED_REQUEST_METADATA",
                                                       self.forwarded_request_metadata),
                                help="Space-delimited list of http request metadata keys to forward "
                                     "to logs/other requests")
        arg_parser.add_argument("--usage_logger_metadata", type=str,
                                default=os.environ.get("AGENT_USAGE_LOGGER_METADATA", ""),
                                help="Space-delimited list of http request metadata keys to forward "
                                     "to models usage statistics logger")
        arg_parser.add_argument("--openapi_service_spec_path", type=str,
                                default=os.environ.get("AGENT_OPENAPI_SPEC",
                                                       self.service_openapi_spec_file),
                                help="File path to OpenAPI service specification document.")
        arg_parser.add_argument("--manifest_update_period_seconds", type=int,
                                default=int(os.environ.get("AGENT_MANIFEST_UPDATE_PERIOD_SECONDS", "0")),
                                help="Periodic run-time update period for manifest in seconds."
                                     " Value <= 0 disables updates.")
        arg_parser.add_argument("--temporary_network_update_period_seconds", type=int,
                                default=int(os.environ.get("AGENT_TEMPORARY_NETWORK_UPDATE_PERIOD_SECONDS", "0")),
                                help="Periodic run-time update period for temporary networks in seconds."
                                     " Value <= 0 disables updates.")
        arg_parser.add_argument("--http_connections_backlog", type=int,
                                default=int(os.environ.get("AGENT_HTTP_CONNECTIONS_BACKLOG",
                                                           DEFAULT_HTTP_CONNECTIONS_BACKLOG)),
                                help="Size of backlog for TCP connections to http server.")
        arg_parser.add_argument("--http_idle_connections_timeout", type=int,
                                default=int(os.environ.get("AGENT_HTTP_IDLE_CONNECTIONS_TIMEOUT",
                                                           DEFAULT_HTTP_IDLE_CONNECTIONS_TIMEOUT_SECONDS)),
                                help="Timeout in seconds before idle and alive connection to http server"
                                     "will be closed")
        arg_parser.add_argument("--http_server_instances", type=int,
                                default=int(os.environ.get("AGENT_HTTP_SERVER_INSTANCES",
                                                           DEFAULT_HTTP_SERVER_INSTANCES)),
                                help="Number of http server instances to be created "
                                     "one instance per separate process")
        arg_parser.add_argument("--http_resources_monitor_interval_seconds", type=int,
                                default=int(os.environ.get("AGENT_HTTP_RESOURCES_MONITOR_INTERVAL",
                                                           DEFAULT_HTTP_SERVER_MONITOR_INTERVAL_SECONDS)),
                                help="Http server resources monitoring/logging interval in seconds "
                                     "0 means no logging")
        arg_parser.add_argument("--mcp_enable", type=str,
                                default=os.environ.get("AGENT_MCP_ENABLE", "true"),
                                help="'true' if MCP protocol service should be enabled")
        arg_parser.add_argument("--mcp_only", type=str,
                                default=os.environ.get("AGENT_MCP_ONLY", "false"),
                                help="'true' if only MCP protocol service will be run (no HTTP service)")
        return arg_parser

    def parse_args(self):
        """
        Parse command-line arguments into member variables
        """
        arg_parser: ArgumentParser = self.prepare_args()

        # Actually parse the args into class variables

        # Incorrectly flagged as Path Traversal 3, 7
        # See destination below ~ line 139, 154 for explanation.
        args = arg_parser.parse_args()

        self.server_name = args.server_name
        server_status = ServerStatus(self.server_name)
        self.server_context.set_server_status(server_status)

        self.http_port = args.http_port
        if self.http_port == 0:
            server_status.http_service.set_requested(False)
        self.server_context.set_server_port(self.http_port)

        self.server_name_for_logs = args.server_name_for_logs
        self.max_concurrent_requests = args.max_concurrent_requests
        self.request_limit = args.request_limit
        self.forwarded_request_metadata = args.forwarded_request_metadata
        if not self.forwarded_request_metadata:
            self.forwarded_request_metadata = ""
        self.usage_logger_metadata = args.usage_logger_metadata
        if not self.usage_logger_metadata:
            self.usage_logger_metadata = self.forwarded_request_metadata
        self.service_openapi_spec_file = args.openapi_service_spec_path

        if args.manifest_update_period_seconds <= 0 and \
                args.temporary_network_update_period_seconds <= 0:
            # StorageWatcher is disabled:
            server_status.updater.set_requested(False)
        if args.temporary_network_update_period_seconds <= 0:
            # We don't need the queues in this situation either.
            # This is a signal to other code to not even bother with Reservationists
            self.server_context.no_queues()
        # Do we to enable MCP service?
        if args.mcp_enable.lower() != "true":
            server_status.mcp_service.set_requested(False)
        if args.mcp_only.lower() == "true":
            server_status.mcp_service.set_requested(True)
            # Disable HTTP service if MCP only is requested
            server_status.http_service.set_requested(False)

        self.http_server_config.http_connections_backlog = args.http_connections_backlog
        self.http_server_config.http_idle_connection_timeout_seconds = args.http_idle_connections_timeout
        self.http_server_config.http_server_instances = args.http_server_instances
        self.http_server_config.http_server_monitor_interval_seconds = args.http_resources_monitor_interval_seconds
        self.http_server_config.http_port = args.http_port

        manifest_restorer = RegistryManifestRestorer()
        manifest_agent_networks: Dict[str, Dict[str, AgentNetwork]] = manifest_restorer.restore()
        manifest_files: List[str] = manifest_restorer.get_manifest_files()

        self.watcher_config = {
            "manifest_path": manifest_files,
            "manifest_update_period_seconds": args.manifest_update_period_seconds,
            "temporary_network_update_period_seconds": args.temporary_network_update_period_seconds
        }

        self.agent_networks = manifest_agent_networks

    def _get_default_openapi_spec_path(self) -> str:
        """
        Return a file path to default location of OpenAPI specification file
        for neuro-san service.
        """
        return TOP_LEVEL_DIR.get_file_in_basis("api/grpc/agent_service.json")

    def main_loop(self):
        """
        Command line entry point
        """
        self.parse_args()

        # Make for easy running from the neuro-san repo
        if os.environ.get("AGENT_SERVICE_LOG_JSON") is None:
            # Use the log file that is local to the repo
            os.environ["AGENT_SERVICE_LOG_JSON"] = DEPLOY_DIR.get_file_in_basis("logging.json")

        # Construct forwarded metadata list as a union of
        # self.forwarded_request_metadata and self.usage_logger_metadata
        metadata_set = set(self.forwarded_request_metadata.split())
        metadata_set = metadata_set | set(self.usage_logger_metadata.split())
        metadata_str: str = " ".join(sorted(metadata_set))

        server_status: ServerStatus = self.server_context.get_server_status()

        # Fast out if neither http service nor MCP service are requested:
        if not server_status.http_service.is_requested() and \
                not server_status.mcp_service.is_requested():
            print("HTTP server is not requested - exiting.")
            return

        # List of components which should be started after http server is created
        # and have spun up all its instances:
        components_to_start: List[Startable] = []
        if server_status.updater.is_requested():
            current_dir: str = os.path.dirname(os.path.abspath(__file__))
            setup_logging(server_status.updater.get_service_name(),
                          current_dir,
                          'AGENT_SERVICE_LOG_JSON',
                          'AGENT_SERVICE_LOG_LEVEL')
            watcher = StorageWatcher(self.watcher_config, self.server_context)
            components_to_start.append(watcher)

        # Create HTTP server;
        self.http_server = HttpServer(
            self.server_context,
            self.http_server_config,
            self.service_openapi_spec_file,
            self.request_limit,
            forwarded_request_metadata=metadata_str)

        # Enable MCP service if requested:
        if server_status.mcp_service.is_requested():
            self.server_context.get_mcp_server_context().set_enabled(True)

        # Now - our http server is created and listens to updates of network_storage
        # Perform the initial setup
        network_storage_dict: Dict[str, AgentNetworkStorage] = self.server_context.get_network_storage_dict()
        for storage_type in ["public", "protected"]:
            storage: AgentNetworkStorage = network_storage_dict.get(storage_type)
            storage.setup_agent_networks(self.agent_networks.get(storage_type))

        # Start http server:
        self.http_server.start(components_to_start)


if __name__ == '__main__':
    ServerMainLoop().main_loop()
