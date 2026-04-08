
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
from typing import List

import http
import os

from http import HTTPStatus

from importlib.metadata import version as library_version
from importlib.metadata import PackageNotFoundError

from tornado.web import RequestHandler
from neuro_san.service.http.logging.http_logger import HttpLogger
from neuro_san.service.utils.server_status import ServerStatus


class HealthCheckHandler(RequestHandler):
    """
    Handler class for API endpoint health check.
    """

    # pylint: disable=attribute-defined-outside-init
    def initialize(self,
                   forwarded_request_metadata: List[str],
                   server_status: ServerStatus,
                   op: str,
                   logging_config: Dict[str, Any]):
        """
        This method is called by Tornado framework to allow
        injecting service-specific data into local handler context.
        Here we use it to inject CORS headers if so configured.
        :param forwarded_request_metadata: list of client metadata keys;
        :param server_status: current server status to query;
        :param op: requested healthcheck operation:
                   "ready" for /readyz query
                   "live" for /livez query
        :param logging_config: logging configuration dictionary
        """
        self.logger = HttpLogger(forwarded_request_metadata, logging_config)
        if op == "ready":
            self.status = server_status.is_server_ready()
        else:
            self.status = server_status.is_server_live()
        self.server_name = server_status.get_server_name()

        if os.environ.get("AGENT_ALLOW_CORS_HEADERS") is not None:
            self.set_header("Access-Control-Allow-Origin", "*")
            self.set_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.set_header("Access-Control-Allow-Headers", "Content-Type, Transfer-Encoding")

    async def get(self):
        """
        Implementation of GET request handler for API health check.
        """

        try:
            if self.status:
                versions: Dict[str, Any] = self.determine_versions()
                result_dict: Dict[str, Any] = {
                    "service": self.server_name,
                    "status": "ok",
                    "versions": versions
                }
                self.set_header("Content-Type", "application/json")
                self.write(result_dict)
            else:
                # Set "service unavailable" status
                self.set_status(HTTPStatus.SERVICE_UNAVAILABLE)
                self.write({"error": "Service Unavailable"})
        except Exception:  # pylint: disable=broad-exception-caught
            # Handle unexpected errors
            self.set_status(HTTPStatus.INTERNAL_SERVER_ERROR)
            self.write({"error": "Internal server error"})
        finally:
            self.finish()

    def get_metadata(self) -> Dict[str, Any]:
        """
        Get request metadata
        """
        return {}

    def data_received(self, chunk):
        """
        Method overrides abstract method of RequestHandler
        with no-op implementation.
        """
        return

    async def options(self, *_args, **_kwargs):
        """
        Handles OPTIONS requests for CORS support
        """
        # No body needed. Just return a 204 No Content
        self.set_status(http.HTTPStatus.NO_CONTENT)
        self.finish()

    def determine_versions(self) -> Dict[str, Any]:
        """
        Allow for a list of libraries to report versioning.
        We have a static list that we always support, but also look at the
        AGENT_VERSION_LIBS env var (if set) to potentially report more.
        :return: A dictionary whose keys are libraries and whose values are the
                 versions installed for those libraries.
        """
        versions: Dict[str, Any] = {}

        # Start with a static list of libs we always support
        versioned_libs: List[str] = ["neuro-san"]

        # Try to incorporate libs from the env var.
        env_var_libs: str = os.environ.get("AGENT_VERSION_LIBS")
        if env_var_libs is not None:
            for env_var_lib in env_var_libs.split(" "):
                if env_var_lib is None:
                    # Skip anything with nothing in it
                    continue

                env_var_lib = env_var_lib.strip()
                if len(env_var_lib) == 0:
                    # Skip anything with nothing in it
                    continue

                if ":" not in env_var_lib:
                    # Look for the library in the versioning loop below
                    versioned_libs.append(env_var_lib)
                    continue

                # We have a version coming in from the env var
                version: str = env_var_lib.split(":")[1]
                env_var_lib = env_var_lib.split(":")[0]
                versions[env_var_lib] = version

        for lib in versioned_libs:
            # Did we already find a version from the env var?
            version: str = versions.get(lib)
            if version is None:
                try:
                    # Try getting the pip-installed version from the system
                    version = str(library_version(lib))
                except PackageNotFoundError:
                    # Don't know what to do, so report a shrug.
                    version = "unknown"
                versions[lib] = version

        return versions
