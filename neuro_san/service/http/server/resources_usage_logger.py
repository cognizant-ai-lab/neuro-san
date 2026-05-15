
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

from typing import Any
from typing import Dict
import json
import tornado

from neuro_san.service.http.logging.http_logger import HttpLogger
from neuro_san.internals.interfaces.startable import Startable
from neuro_san.service.utils.service_resources import ServiceResources


class ResourcesUsageLogger(Startable):
    """
    Class for periodic logging of server run-time resource usage:
    file descriptors and open inet connections on server port.
    """

    def __init__(self, log_interval_seconds: int, http_port: int, logger: HttpLogger):
        """
        Constructor
        :param log_interval_seconds: interval in seconds between logging resource usage
        :param http_port: http port to use
        :param logger: HttpLogger instance for logging
        """
        self.log_interval_seconds = log_interval_seconds
        self.http_port: int = http_port
        self.logger: HttpLogger = logger
        self.periodic_callback = tornado.ioloop.PeriodicCallback(
            self.run_resources_usage,
            self.log_interval_seconds * 1000
        )

    def log_resources_usage(self):
        """
        Log current usage of server run-time resources:
        file descriptors and open inet connections on server port.
        """
        snapshot_dict: Dict[str, Any] = ServiceResources.get_snapshot_dict(self.http_port)
        self.logger.info({}, "Used: %s", json.dumps(snapshot_dict, indent=4))

    async def run_resources_usage(self):
        """
        Execute collecting and logging of server run-time resources
        in on-blocking mode w.r.t. server event loop.
        This is done because enumerating of some system resources
        could be relatively slow.
        """
        loop = tornado.ioloop.IOLoop.current()
        return await loop.run_in_executor(None, self.log_resources_usage)

    def start(self):
        """
        Start periodic logging of resource usage.
        """
        self.periodic_callback.start()
