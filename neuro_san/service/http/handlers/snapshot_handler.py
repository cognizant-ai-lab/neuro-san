
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
from typing import Any, Dict
import os
import json
import logging
from http import HTTPStatus

from tornado.web import RequestHandler

from neuro_san.service.utils.service_resources import ServiceResources


class SnapshotHandler(RequestHandler):
    """
    Handler class for executing system run-time snapshot query via HTTP API calls.
    """

    # pylint: disable=attribute-defined-outside-init
    def initialize(self, **kwargs):
        """
        This method is called by Tornado framework to allow
        injecting service-specific data into local handler context.
        :param kwargs: dictionary of named parameters, including:
            "http_port" - HTTP server port;
        """
        # Set up local members from kwargs dictionary passed in:
        self.http_port: int = int(kwargs.pop("http_port"))
        self.logger = logging.getLogger(self.__class__.__name__)
        self.is_enabled: bool = os.getenv("ENABLE_RUN_TIME_STATISTICS", "false").lower() == "true"

    async def get(self):
        """
        Implementation of GET request handler for system snapshot query.
        """
        if self.is_enabled:
            snapshot_dict: Dict[str, Any] = ServiceResources.get_snapshot_dict(self.http_port)
            self.write(json.dumps(snapshot_dict, indent=4))
            self.logger.info("Returned system snapshot: %s", json.dumps(snapshot_dict, indent=4))
        else:
            self.set_status(HTTPStatus.SERVICE_UNAVAILABLE)
            self.write("Run-time statistics collection is disabled. "
                       "To enable it, set environment variable ENABLE_RUN_TIME_STATISTICS to 'true'.")
            self.logger.info("Run-time statistics collection is disabled.")

    def data_received(self, chunk):
        """
        This method is required to be implemented as part of RequestHandler subclass,
        but is not used in our case as we do not expect any data in the request body.
        """
