
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
from typing import Any, Dict, Optional
import os
import json
from json.decoder import JSONDecodeError
import logging

from http import HTTPStatus
from tornado.web import RequestHandler

from neuro_san.service.utils.request_util import RequestUtil

try:
    import yappi
    HAS_PROFILER = True
except ImportError:
    HAS_PROFILER = False


class ProfilerControlHandler(RequestHandler):
    """
    Handler class for controlling run-time profiler (yappi) via HTTP API calls.
    """

    async def post(self):
        """
        Implementation of POST request handler for profiler control.
        """
        is_enabled: bool = os.getenv("ENABLE_RUN_TIME_STATISTICS", "false").lower() == "true"
        logger = logging.getLogger(self.__class__.__name__)

        if not is_enabled:
            self.set_status(HTTPStatus.SERVICE_UNAVAILABLE)
            self.write("Run-time profiler is disabled. "
                       "To enable it, set environment variable ENABLE_RUN_TIME_STATISTICS to 'true'.")
            logger.info("Run-time profiler is disabled.")
            return

        if not HAS_PROFILER:
            self.set_status(HTTPStatus.SERVICE_UNAVAILABLE)
            self.write("Profiler library yappi is not available. Please install it with 'pip install yappi'")
            self.logger.info("Profiler library yappi is not available. Please install it with 'pip install yappi'")
            return

        action: Optional[str] = None
        profiler_data_path: Optional[str] = None

        # Parse the JSON request body:
        request_dict: Dict[str, Any] = None
        try:
            # Parse JSON body
            request_dict = json.loads(self.request.body)
            action = request_dict.get("action", "none").lower()
            profiler_data_path = request_dict.get("profiler_data_path")
        except JSONDecodeError as exc:
            self.set_status(HTTPStatus.BAD_REQUEST)
            self.write("Invalid JSON in request body")
            logger.info("Invalid JSON in request body: %s", str(exc))
            return

        try:
            if action == "start":
                # Set clock type to "wall" time to get more accurate profiling results in async code
                yappi.set_clock_type("wall")
                yappi.start()
                self.write("profiling started")
                logger.info("PROFILER STARTED")
            elif action == "stop":
                yappi.stop()
                stats = yappi.get_func_stats()
                # pylint: disable=no-member
                stats.save(profiler_data_path, type="pstat")
                self.write(f"profiling stopped and saved to {RequestUtil.safe_message(str(profiler_data_path))}")
                logger.info("PROFILER STOPPED AND SAVED TO %s", profiler_data_path)
            else:
                self.write("Invalid profiler control action. Expected 'start' or 'stop'.")
                logger.info("Invalid profiler control action received: %s", action)
                self.set_status(HTTPStatus.BAD_REQUEST)
        except Exception as exception:  # pylint: disable=broad-exception-caught
            logger.error("Error during profiler control operation '%s': %s",
                         action, str(exception), exc_info=True)
            self.write(f"FAILED to {RequestUtil.safe_message(str(action))} profiler")
            self.set_status(HTTPStatus.INTERNAL_SERVER_ERROR)

    def data_received(self, chunk):
        """
        This method is required to be implemented as part of RequestHandler subclass,
        but is not used in our case as we do not expect any data in the request body.
        """
