
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

from neuro_san.service.utils.service_status import ServiceStatus


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
        self.http_service: ServiceStatus = ServiceStatus("http")
        self.updater: ServiceStatus = ServiceStatus("updater")
        self.mcp_service: ServiceStatus = ServiceStatus("mcp")

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
            (not self.http_service.is_requested() or self.http_service.is_ready()) and \
            (not self.mcp_service.is_requested() or self.mcp_service.is_ready()) and \
            (not self.updater.is_requested() or self.updater.is_ready())

    def get_server_name(self) -> str:
        """
        Return server name
        """
        return self.server_name
