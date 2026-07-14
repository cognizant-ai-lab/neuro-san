
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

from typing import Any
from typing import Dict
from typing import List
from typing import Optional

import os

from importlib.metadata import version as library_version
from importlib.metadata import PackageNotFoundError

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

        # Library versions are process-invariant: they depend on what pip
        # installed (or on AGENT_VERSION_LIBS which is read once at startup)
        # and do not change over the server's lifetime. Compute them once
        # here so health-check requests do not re-run importlib.metadata
        # lookups on every probe.
        self._versions: Optional[Dict[str, Any]] = None

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

    def get_versions(self) -> Dict[str, Any]:
        """
        Return a mapping of library name -> installed version, suitable for
        inclusion in health-check responses. Computed on first access and
        cached, since library versions do not change over a process's
        lifetime.

        Always includes the neuro-san version. The AGENT_VERSION_LIBS env
        var can add more entries: it is parsed as a space-delimited list
        where each entry is either a library name (in which case the
        version is looked up via importlib.metadata) or "name:version"
        (in which case the version is taken verbatim from the env var --
        useful for libraries that are not pip-installed, such as a checked-
        out neuro-san source tree whose "version" should be a repo tag).

        :return: A dict of {library_name: version_string}. Libraries whose
                 versions cannot be resolved are reported as "unknown".
        """
        if self._versions is None:
            self._versions = self._resolve_versions()
        return self._versions

    @staticmethod
    def _resolve_versions() -> Dict[str, Any]:
        """
        One-shot version resolver: reads AGENT_VERSION_LIBS, resolves any
        listed libraries via importlib.metadata, and returns the combined
        mapping. See get_versions() for the semantics of the env var.
        """
        versions: Dict[str, Any] = {}

        # Static baseline -- always report neuro-san.
        versioned_libs: List[str] = ["neuro-san"]

        # AGENT_VERSION_LIBS can add libraries and/or pre-declared versions.
        env_var_libs: str = os.environ.get("AGENT_VERSION_LIBS")
        if env_var_libs is not None:
            for env_var_lib in env_var_libs.split(" "):
                if env_var_lib is None:
                    continue

                env_var_lib = env_var_lib.strip()
                if len(env_var_lib) == 0:
                    continue

                if ":" not in env_var_lib:
                    # No explicit version; queue for lookup.
                    versioned_libs.append(env_var_lib)
                    continue

                # Explicit version handed to us via env var; take it as-is.
                # This is useful when running from a source tree where the
                # library isn't pip-installed.
                lib_version: str = env_var_lib.split(":")[1]
                env_var_lib = env_var_lib.split(":")[0]
                versions[env_var_lib] = lib_version

        for lib in versioned_libs:
            if versions.get(lib) is not None:
                # Already set from the env var (would happen if the same
                # library name appears both bare and with a colon).
                continue
            try:
                versions[lib] = str(library_version(lib))
            except PackageNotFoundError:
                versions[lib] = "unknown"

        return versions
