
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
from typing import Optional
import logging

import asyncio

try:
    import yappi
    HAS_PROFILER = True
except ImportError:
    HAS_PROFILER = False

from http import HTTPStatus
from tornado.web import RequestHandler


class ProfilerControlHandler(RequestHandler):
    """
    Handler class for controlling run-time profiler (yappi) via HTTP API calls.
    """
    # pylint: disable=attribute-defined-outside-init
    def initialize(self,
                   op: str,
                   prof_data_path: Optional[str]):
        """
        This method is called by Tornado framework to allow
        injecting service-specific data into local handler context.
        :param op: requested profiler operation:
                   "start" for starting run-time profiler
                   "stop" for stopping profiler
        :param prof_data_path: optional path to save profiler data when stopping profiler;
            if not provided, data will be saved in current working directory with default name "profile.prof"
        """
        self.op: str = op
        self.prof_data_path: Optional[str] = prof_data_path
        if self.prof_data_path is None:
            self.prof_data_path = "profile.prof"
        self.logger = logging.getLogger(self.__class__.__name__)

    async def get(self):
        """
        Implementation of GET request handler for profiler control.
        """
        if not HAS_PROFILER:
            self.set_status(HTTPStatus.SERVICE_UNAVAILABLE)
            self.write("Profiler library yappi is not available. Please install it with 'pip install yappi'")
            self.logger.info("Profiler library yappi is not available. Please install it with 'pip install yappi'")
            return

        try:
            if self.op == "start":
                # Set clock type to "wall" time to get more accurate profiling results in async code
                yappi.set_clock_type("wall")
                yappi.start()
                self.write("profiling started")
                self.logger.info("PROFILER STARTED")
            else:
                yappi.stop()
                stats = yappi.get_func_stats()
                stats.save(self.prof_data_path, type="pstat")
                self.write(f"profiling stopped and saved to {self.prof_data_path}")
                self.logger.info("PROFILER STOPPED AND SAVED TO %s", self.prof_data_path)
        except Exception as exception:  # pylint: disable=broad-exception-caught
            self.logger.error("Error during profiler control operation '%s': %s",
                              self.op, str(exception), exc_info=True)
            self.write(f"FAILED to {self.op} profiler")
            self.set_status(HTTPStatus.INTERNAL_SERVER_ERROR)

    def data_received(self, chunk):
        """
        This method is required to be implemented as part of RequestHandler subclass,
        but is not used in our case as we do not expect any data in the request body.
        """
        pass
