
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

class ServiceStatus:
    """
    Class for registering and reporting overall status of the service,
    primarily for interaction with external deployment environment.
    """

    def __init__(self, service_name: str):
        """
        Constructor.
        """
        self.service_name: str = service_name
        self.service_requested: bool = True
        self.service_ready: bool = False

    def set_status(self, status: bool):
        """
        Set the status of a service
        """
        self.service_ready = status

    def is_ready(self) -> bool:
        """
        True if service is ready
        """
        return self.service_ready

    def set_requested(self, requested: bool):
        """
        Set if a service is requested by neuro-san server.
        """
        self.service_requested = requested

    def is_requested(self) -> bool:
        """
        True if service is requested.
        """
        return self.service_requested

    def get_service_name(self) -> str:
        """
        Return service name
        """
        return self.service_name
