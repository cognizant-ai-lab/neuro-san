
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

DEFAULT_HTTP_CONNECTIONS_BACKLOG: int = 128
DEFAULT_HTTP_IDLE_CONNECTIONS_TIMEOUT_SECONDS: int = 3600
DEFAULT_HTTP_SERVER_INSTANCES: int = 1
DEFAULT_HTTP_SERVER_MONITOR_INTERVAL_SECONDS: int = 0
DEFAULT_KEEP_ALIVE_INTERVAL_SECONDS: int = 0


class HttpServerConfig:
    """
    Class aggregating Tornado http server run-time configuration parameters.
    """

    def __init__(self):
        self.http_connections_backlog: int = DEFAULT_HTTP_CONNECTIONS_BACKLOG
        self.http_idle_connection_timeout_seconds: int = DEFAULT_HTTP_IDLE_CONNECTIONS_TIMEOUT_SECONDS
        self.http_server_instances: int = DEFAULT_HTTP_SERVER_INSTANCES
        self.http_port: int = 80
        self.http_server_monitor_interval_seconds: int = DEFAULT_HTTP_SERVER_MONITOR_INTERVAL_SECONDS
        self.http_server_heartbeat_interval_seconds: int = DEFAULT_KEEP_ALIVE_INTERVAL_SECONDS
