
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
    print("yappi library is required for profiling. Please install it with 'pip install yappi'")

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

    @staticmethod
    def get_profiler_context_id() -> int:
        """
        Get the context ID for the current execution context, which is used by yappi to differentiate
        between different threads or async tasks. In this case, we use the ID of the current asyncio task.
        If there is no current task (e.g., if we're not in an async context), we return 0.
        """
        try:
            print("Getting profiler context ID for current asyncio task...")
            task_id = id(asyncio.current_task())
            if task_id:
                return 1   #task_id & 0x7FFFFFFF  # yappi expects a 32-bit integer context ID
            return 0
        except RuntimeError:
            # This can happen if we're not in an async context, so we return 0 as the default context ID.
            print(f"Error getting profiler context ID: RuntimeError")
            return 0
        except Exception as exc:  # pylint: disable=broad-exception-caught
            print(f"Error getting profiler context ID: {str(exc)}")
            return 0

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
                #yappi.set_context_id_callback(ProfilerControlHandler.get_profiler_context_id)
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
