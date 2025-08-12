
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

DEFAULT_HTTP_CONNECTIONS_BACKLOG: int = 128
DEFAULT_HTTP_IDLE_CONNECTIONS_TIMEOUT_SECONDS: int = 3600
DEFAULT_HTTP_SERVER_INSTANCES: int = 1
DEFAULT_HTTP_SERVER_MONITOR_INTERVAL_SECONDS: int = 10


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
