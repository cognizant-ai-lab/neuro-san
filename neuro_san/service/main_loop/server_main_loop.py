
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
from typing import Dict
from typing import List

import os
import threading

from argparse import ArgumentParser

from leaf_server_common.server.server_loop_callbacks import ServerLoopCallbacks

from neuro_san.interfaces.agent_session import AgentSession
from neuro_san.internals.graph.persistence.registry_manifest_restorer import RegistryManifestRestorer
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.utils.file_of_class import FileOfClass
from neuro_san.service.grpc.grpc_agent_server import DEFAULT_SERVER_NAME
from neuro_san.service.grpc.grpc_agent_server import DEFAULT_SERVER_NAME_FOR_LOGS
from neuro_san.service.grpc.grpc_agent_server import DEFAULT_MAX_CONCURRENT_REQUESTS
from neuro_san.service.grpc.grpc_agent_server import DEFAULT_REQUEST_LIMIT
from neuro_san.service.grpc.grpc_agent_server import GrpcAgentServer
from neuro_san.service.grpc.grpc_agent_service import GrpcAgentService
from neuro_san.service.http.server.http_sidecar import HttpSidecar
from neuro_san.service.registries_watcher.periodic_updater.manifest_periodic_updater import ManifestPeriodicUpdater


# pylint: disable=too-many-instance-attributes
class ServerMainLoop(ServerLoopCallbacks):
    """
    This class handles the service main loop.
    """

    def __init__(self):
        """
        Constructor
        """
        self.port: int = 0
        self.http_port: int = 0

        self.agent_networks: Dict[str, AgentNetwork] = {}

        self.server_name: str = DEFAULT_SERVER_NAME
        self.server_name_for_logs: str = DEFAULT_SERVER_NAME_FOR_LOGS
        self.max_concurrent_requests: int = DEFAULT_MAX_CONCURRENT_REQUESTS
        self.request_limit: int = DEFAULT_REQUEST_LIMIT
        self.forwarded_request_metadata: int = GrpcAgentServer.DEFAULT_FORWARDED_REQUEST_METADATA
        self.service_openapi_spec_file: str = self._get_default_openapi_spec_path()
        self.manifest_update_period_seconds: int = 0
        self.server: GrpcAgentServer = None
        self.manifest_files: List[str] = []

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
        self.port = args.port
        self.http_port = args.http_port
        self.server_name = args.server_name
        self.server_name_for_logs = args.server_name_for_logs
        self.max_concurrent_requests = args.max_concurrent_requests
        self.request_limit = args.request_limit
        self.forwarded_request_metadata = args.forwarded_request_metadata
        self.service_openapi_spec_file = args.openapi_service_spec_path
        self.manifest_update_period_seconds = args.manifest_update_period_seconds

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

        self.server = GrpcAgentServer(self.port,
                                      server_loop_callbacks=self,
                                      agent_networks=self.agent_networks,
                                      server_name=self.server_name,
                                      server_name_for_logs=self.server_name_for_logs,
                                      max_concurrent_requests=self.max_concurrent_requests,
                                      request_limit=self.request_limit,
                                      forwarded_request_metadata=self.forwarded_request_metadata)

        if self.manifest_update_period_seconds > 0:
            manifest_file: str = self.manifest_files[0]
            updater: ManifestPeriodicUpdater =\
                ManifestPeriodicUpdater(manifest_file, self.manifest_update_period_seconds)
            updater.start()

        # Start HTTP server side-car:
        http_sidecar = HttpSidecar(
            self.server.get_starting_event(),
            self.port,
            self.http_port,
            self.service_openapi_spec_file,
            self.request_limit,
            forwarded_request_metadata=self.forwarded_request_metadata)
        http_server_thread = threading.Thread(target=http_sidecar, args=(self.server,), daemon=True)
        http_server_thread.start()

        self.server.serve()

    def loop_callback(self) -> bool:
        """
        Periodically called by the main server loop of ServerLifetime.
        """
        # Report back on service activity so the ServerLifetime that calls
        # this method can properly yield/sleep depending on how many requests
        # are in motion.
        agent_services: List[GrpcAgentService] = self.server.get_services()
        for agent_service in agent_services:
            if agent_service.get_request_count() > 0:
                return True

        return False


if __name__ == '__main__':
    ServerMainLoop().main_loop()
