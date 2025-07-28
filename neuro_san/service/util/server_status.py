
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

from neuro_san.service.util.service_status import ServiceStatus


class ServerStatus:
    """
    Class for registering and reporting overall status of the server,
    primarily for interaction with external deployment environment.
    """

    def __init__(self, server_name: str):
        """
        Constructor.
        """
        self.server_name: str = server_name
        self.grpc_service: ServiceStatus = ServiceStatus("gRPC")
        self.http_service: ServiceStatus = ServiceStatus("http")
        self.updater: ServiceStatus = ServiceStatus("updater")

    def is_server_live(self) -> bool:
        """
        Return "live" status for the server
        """
        # If somebody calls this, we are at least alive
        return True

    def is_server_ready(self) -> bool:
        """
        Return "ready" status for the server
        """
        return \
            (not self.grpc_service.is_requested() or self.grpc_service.is_ready()) and \
            (not self.http_service.is_requested() or self.http_service.is_ready()) and \
            (not self.updater.is_requested() or self.updater.is_ready())

    def get_server_name(self) -> str:
        """
        Return server name
        """
        return self.server_name
