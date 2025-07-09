
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

class ServerStatus:
    """
    Class for registering and reporting overall status of the server,
    primarily for interaction with external deployment environment.
    """

    def __init__(self):
        """
        Constructor.
        """
        self.grpc_service_ready: bool = False
        self.http_service_ready: bool = False
        self.updater_ready: bool = False

    def set_grpc_status(self, status: bool):
        """
        Set the status of gRPC service
        """
        self.grpc_service_ready = status

    def set_http_status(self, status: bool):
        """
        Set the status of http service
        """
        self.http_service_ready = status

    def set_updater_status(self, status: bool):
        """
        Set the status of dynamic agents registry updater
        """
        self.updater_ready = status

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
        # If somebody calls this, we are at least alive
        return self.grpc_service_ready and self.http_service_ready and self.updater_ready
