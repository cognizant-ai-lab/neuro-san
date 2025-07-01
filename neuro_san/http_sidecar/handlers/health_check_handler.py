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
from typing import Any
from typing import Dict
from typing import List

import http
import os

from importlib.metadata import version as library_version
from importlib.metadata import PackageNotFoundError

from tornado.web import RequestHandler
from neuro_san.http_sidecar.logging.http_logger import HttpLogger


class HealthCheckHandler(RequestHandler):
    """
    Handler class for API endpoint health check.
    """

    # pylint: disable=attribute-defined-outside-init
    def initialize(self, forwarded_request_metadata: List[str]):
        """
        This method is called by Tornado framework to allow
        injecting service-specific data into local handler context.
        Here we use it to inject CORS headers if so configured.
        """
        self.logger = HttpLogger(forwarded_request_metadata)
        if os.environ.get("AGENT_ALLOW_CORS_HEADERS") is not None:
            self.set_header("Access-Control-Allow-Origin", "*")
            self.set_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.set_header("Access-Control-Allow-Headers", "Content-Type, Transfer-Encoding")

    async def get(self):
        """
        Implementation of GET request handler for API health check.
        """

        try:
            versions: Dict[str, Any] = self.determine_versions()
            result_dict: Dict[str, Any] = {
                "service": "neuro-san agents",
                "status": "healthy",
                "versions": versions
            }
            self.set_header("Content-Type", "application/json")
            self.write(result_dict)
        except Exception:  # pylint: disable=broad-exception-caught
            # Handle unexpected errors
            self.set_status(500)
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
