
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
from typing import List

import os
import threading

from argparse import ArgumentParser

from leaf_server_common.server.server_loop_callbacks import ServerLoopCallbacks
from leaf_server_common.logging.logging_setup import setup_logging

from neuro_san.interfaces.agent_session import AgentSession
from neuro_san.internals.graph.persistence.registry_manifest_restorer import RegistryManifestRestorer
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.network_providers.agent_network_storage import AgentNetworkStorage
from neuro_san.internals.utils.file_of_class import FileOfClass
from neuro_san.service.grpc.grpc_agent_server import DEFAULT_SERVER_NAME
from neuro_san.service.grpc.grpc_agent_server import DEFAULT_SERVER_NAME_FOR_LOGS
from neuro_san.service.grpc.grpc_agent_server import DEFAULT_MAX_CONCURRENT_REQUESTS
from neuro_san.service.grpc.grpc_agent_server import DEFAULT_REQUEST_LIMIT
from neuro_san.service.grpc.grpc_agent_server import GrpcAgentServer
from neuro_san.service.grpc.grpc_agent_service import GrpcAgentService
from neuro_san.service.http.server.http_server import HttpServer
from neuro_san.service.watcher.main_loop.storage_watcher import StorageWatcher
from neuro_san.service.utils.server_status import ServerStatus
from neuro_san.service.utils.server_context import ServerContext


# pylint: disable=too-many-instance-attributes
class ServerMainLoop(ServerLoopCallbacks):
    """
    This class handles the service main loop.
    """

    def __init__(self):
        """
        Constructor
        """
        self.grpc_port: int = 0
        self.http_port: int = 0

        self.agent_networks: Dict[str, AgentNetwork] = {}

        self.server_name: str = DEFAULT_SERVER_NAME
        self.server_name_for_logs: str = DEFAULT_SERVER_NAME_FOR_LOGS
        self.max_concurrent_requests: int = DEFAULT_MAX_CONCURRENT_REQUESTS
        self.request_limit: int = DEFAULT_REQUEST_LIMIT
        self.forwarded_request_metadata: str = GrpcAgentServer.DEFAULT_FORWARDED_REQUEST_METADATA
        self.usage_logger_metadata: str = ""
        self.service_openapi_spec_file: str = self._get_default_openapi_spec_path()
        self.manifest_update_period_seconds: int = 0
        self.grpc_server: GrpcAgentServer = None
        self.http_server: HttpServer = None
        self.manifest_files: List[str] = []
        self.server_context = ServerContext()
        self.watcher_config: Dict[str, Any] = {}

    def parse_args(self):
        """
        Parse command-line arguments into member variables
        """
        # Set up the CLI parser
        arg_parser = ArgumentParser()

        arg_parser.add_argument("--port", type=int,
                                default=int(os.environ.get("AGENT_PORT", AgentSession.DEFAULT_PORT)),
                                help="Port number for the grpc service")
        arg_parser.add_argument("--http_port", type=int,
                                default=int(os.environ.get("AGENT_HTTP_PORT", AgentSession.DEFAULT_HTTP_PORT)),
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

        # Actually parse the args into class variables

        # Incorrectly flagged as Path Traversal 3, 7
        # See destination below ~ line 139, 154 for explanation.
        args = arg_parser.parse_args()
        self.server_name = args.server_name
        server_status = ServerStatus(self.server_name)
        self.server_context.set_server_status(server_status)

        self.grpc_port = args.port
        if self.grpc_port == 0:
            server_status.grpc_service.set_requested(False)
        self.http_port = args.http_port
        if self.http_port == 0:
            server_status.http_service.set_requested(False)

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

        self.watcher_config = {
            "manifest_update_period_seconds": args.manifest_update_period_seconds
        }
        if args.manifest_update_period_seconds <= 0:
            # StorageWatcher is disabled:
            server_status.updater.set_requested(False)

        manifest_restorer = RegistryManifestRestorer()
        manifest_agent_networks: Dict[str, AgentNetwork] = manifest_restorer.restore()
        self.manifest_files = manifest_restorer.get_manifest_files()

        self.agent_networks = manifest_agent_networks

    def _get_default_openapi_spec_path(self) -> str:
        """
        Return a file path to default location of OpenAPI specification file
        for neuro-san service.
        """
        file_of_class = FileOfClass(__file__, path_to_basis="../../api/grpc")
        return file_of_class.get_file_in_basis("agent_service.json")

    def main_loop(self):
        """
        Command line entry point
        """
        self.parse_args()

        # Make for easy running from the neuro-san repo
        if os.environ.get("AGENT_SERVICE_LOG_JSON") is None:
            # Use the log file that is local to the repo
            file_of_class = FileOfClass(__file__, path_to_basis="../../deploy")
            os.environ["AGENT_SERVICE_LOG_JSON"] = file_of_class.get_file_in_basis("logging.json")

        # Construct forwarded metadata list as a union of
        # self.forwarded_request_metadata and self.usage_logger_metadata
        metadata_set = set(self.forwarded_request_metadata.split())
        metadata_set = metadata_set | set(self.usage_logger_metadata.split())
        metadata_str: str = " ".join(sorted(metadata_set))

        server_status: ServerStatus = self.server_context.get_server_status()

        if server_status.grpc_service.is_requested():
            self.grpc_server = GrpcAgentServer(
                self.grpc_port,
                server_loop_callbacks=self,
                server_context=self.server_context,
                server_name=self.server_name,
                server_name_for_logs=self.server_name_for_logs,
                max_concurrent_requests=self.max_concurrent_requests,
                request_limit=self.request_limit,
                forwarded_request_metadata=metadata_str)
            self.grpc_server.prepare_for_serving()

        if server_status.updater.is_requested():
            if not server_status.grpc_service.is_requested():
                current_dir: str = os.path.dirname(os.path.abspath(__file__))
                setup_logging(server_status.updater.get_service_name(),
                              current_dir,
                              'AGENT_SERVICE_LOG_JSON',
                              'AGENT_SERVICE_LOG_LEVEL')
            manifest_file: str = self.manifest_files[0]
            watcher = StorageWatcher(
                    manifest_file,
                    self.watcher_config,
                    self.server_context)
            watcher.start()

        if server_status.http_service.is_requested():
            # Create HTTP server;
            self.http_server = HttpServer(
                self.server_context,
                self.http_port,
                self.service_openapi_spec_file,
                self.request_limit,
                forwarded_request_metadata=metadata_str)

        # Now - our servers (gRPC and http) are created and listen to updates of network_storage
        # Perform the initial setup
        network_storage_dict: Dict[str, AgentNetworkStorage] = self.server_context.get_network_storage_dict()
        public_storage: AgentNetworkStorage = network_storage_dict.get("public")
        public_storage.setup_agent_networks(self.agent_networks)

        # Start all services:
        http_server_thread = None
        if server_status.http_service.is_requested():
            http_server_thread = threading.Thread(target=self.http_server, args=(self.grpc_server,), daemon=True)
            http_server_thread.start()

        if server_status.grpc_service.is_requested():
            self.grpc_server.serve()

        if http_server_thread is not None:
            http_server_thread.join()

    def loop_callback(self) -> bool:
        """
        Periodically called by the main server loop of ServerLifetime.
        """
        # Report back on service activity so the ServerLifetime that calls
        # this method can properly yield/sleep depending on how many requests
        # are in motion.
        agent_services: List[GrpcAgentService] = self.grpc_server.get_services()
        for agent_service in agent_services:
            if agent_service.get_request_count() > 0:
                return True

        return False


if __name__ == '__main__':
    ServerMainLoop().main_loop()
