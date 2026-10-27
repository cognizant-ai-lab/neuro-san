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

from argparse import Namespace
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version
from json import loads
from logging import Logger
from logging import getLogger
from os.path import getmtime
from os.path import isfile
from time import time
from typing import Any
from typing import Dict
from typing import Optional
from urllib.error import URLError
from urllib.request import urlopen

from leaf_common.parsers.dictionary_extractor import DictionaryExtractor

from tests.load_tests.confirm import Confirm
from tests.load_tests.load_test_constants import LoadTestConstants
from tests.load_tests.reporting.sensitive_error_logger import SensitiveErrorLogger
from tests.load_tests.validation.environment_validator import EnvironmentValidator
from tests.load_tests.validation.load_test_abort_error import LoadTestAbortError


class ServerChecker:
    """
    Checks the target server and its log before a load test, and finds the neuro-san version to tag the run with.

    Holds the server version from /healthz once it is read, so every caller gets the same value.
    """

    SECONDS_PER_MINUTE: int = 60

    def __init__(self, args: Namespace) -> None:
        """
        Store the parsed arguments.

        :param args: Parsed command-line arguments
        """
        self.args: Namespace = args
        class_logger: Logger = getLogger(self.__class__.__name__)
        self.logger: SensitiveErrorLogger = SensitiveErrorLogger(class_logger)
        self._server_ns_version: Optional[str] = None

    def preflight_server_check(self) -> None:
        """
        Abort before firing if the target server is unreachable.

        A quick TCP connect to --host:--port catches "server not
        found" (connection refused / DNS failure / host down) so a
        whole run's worth of requests is not fired at nothing.

        :raises LoadTestAbortError: When the server can't be reached
        """
        host: str = self.args.host
        port: int = self.args.port
        if EnvironmentValidator.is_port_open(host, port):
            self.logger.info("  Preflight: server %s:%s reachable.", host, port)
            self._server_ns_version = self.fetch_server_version()
            if self._server_ns_version:
                self.logger.info("  Preflight: server neuro-san version %s.", self._server_ns_version)
            else:
                self.logger.info("  Preflight: server version unavailable (no /healthz response).")
            return
        scheme: str = self._scheme()
        self.logger.error(
            """ABORT: server %s:%s (%s) is unreachable — not firing any requests.
  Check --host/--port/--https, or start the server.""",
            host, port, scheme,
        )
        raise LoadTestAbortError(1)

    def fetch_server_version(self) -> Optional[str]:
        """
        Return the server's neuro-san version via its /healthz API.

        Queries ``<scheme>://<host>:<port>/healthz`` (the same HTTP
        endpoint the client already reaches, so it works remotely
        without any access to the server machine) and reads
        ``versions['neuro-san']``.

        :return: The server's version, or None if the endpoint is
                 unreachable or unparseable (e.g. an older/gRPC-only server)
        """
        scheme: str = self._scheme()
        url: str = f"{scheme}://{self.args.host}:{self.args.port}/healthz"
        response_bytes: bytes = b""
        response_text: str = ""
        payload: Dict[str, Any] = {}
        extractor: Optional[DictionaryExtractor] = None
        server_version: Optional[str] = None
        try:
            with urlopen(url, timeout=LoadTestConstants.SOCKET_CHECK_TIMEOUT_SECONDS) as response:
                response_bytes = response.read()
                response_text = response_bytes.decode("utf-8")
                payload = loads(response_text)
            extractor = DictionaryExtractor(payload)
            server_version = extractor.get("versions.neuro-san")
            return server_version
        except (URLError, OSError, ValueError) as exc:
            self.logger.debug("Could not fetch server version from %s: %s", url, exc)
            return None

    def resolve_ns_version(self) -> Optional[str]:
        """
        Return the neuro-san version to tag this run with.

        Prefers the *server's* version (via ``/healthz``) so the tag
        reflects what is actually being exercised, even when the client
        runs from a different checkout/venv or a remote machine.  The
        result is cached in ``_server_ns_version``.  Falls back to the
        locally installed package version when the server is
        unreachable or does not report one.

        :return: The server's version, else the local package version, or None
        """
        if not self._server_ns_version:
            self._server_ns_version = self.fetch_server_version()
        neuro_san_version: Optional[str] = self._server_ns_version
        if not neuro_san_version:
            neuro_san_version = ServerChecker.get_package_version("neuro-san")
        return neuro_san_version

    def get_server_ns_version(self) -> Optional[str]:
        """
        Return the neuro-san version the server reported, without the local package fallback.

        :return: The cached server version, or None when the server has not reported one
        """
        return self._server_ns_version

    def validate_server_log(self) -> Optional[int]:
        """
        Validate --server-log path when provided.

        Skips validation when --server-log is used without a path
        (auto-detect mode, value is ``"auto"``).  At norm/adv levels
        without --server-log, logs a warning listing which features
        will be unavailable.

        :return: The stale log age in minutes, or None when the log is not stale, not given, or "auto"
        :raises LoadTestAbortError: When the --server-log file is not found
        """
        level: str = self.args.level
        server_log: Optional[str] = self.args.server_log

        if server_log == "auto":
            return None

        if level == LoadTestConstants.LEVEL_MIN and not server_log:
            return None

        if not server_log:
            self.logger.warning(
                """No --server-log provided at %s level.
  The following will be unavailable:
    - Retry counts and amplification factor
    - Server-side request validation
    - Client disconnection detection
    - Per-agent-network token breakdown (server log only)
  Resource monitoring (psutil) and aggregated token accounting (--tokens) still work.
  To enable full analysis, add:
    --server-log  (auto-detect)
    --server-log logs/server.log""",
                level,
            )
            return None

        if not isfile(server_log):
            self.logger.error("Server log not found: %s", server_log)
            raise LoadTestAbortError(1)

        modification_time: float = getmtime(server_log)
        age_seconds: float = time() - modification_time
        # Whole minutes, e.g. 150.7 seconds -> 2 minutes
        age_minutes: int = int(age_seconds / ServerChecker.SECONDS_PER_MINUTE)
        if age_seconds > LoadTestConstants.STALE_LOG_THRESHOLD_SECONDS:
            return age_minutes
        return None

    def confirm_no_server_log(self, level: str) -> None:
        """
        Prompt to continue when a local server.log isn't found.

        norm/adv expect a server log; if auto-detect fails, offer to
        run without it or abort. --no-server-log skips this prompt;
        --no-dry-run does not (it only bypasses the cost confirmation).

        :param level: The --level value
        :raises LoadTestAbortError: When the user chooses not to continue
        """
        self.logger.warning(
            """Server log not found for --level %s. Without it: no retry, disconnection, or pool analysis.
  Set it with --server-log <path>, or use --no-server-log to skip this prompt.""",
            level,
        )
        if not Confirm.ask("Continue without server-log analysis?"):
            self.logger.info("Aborted by user.")
            raise LoadTestAbortError(0)
        self.logger.info("  Continuing without server-log analysis.")

    @staticmethod
    def get_package_version(package_name: str) -> Optional[str]:
        """
        Return the installed version of a package, or None.

        :param package_name: Name of the installed package
        :return: The version, or None when the package is not installed
        """
        package_version: Optional[str] = None
        try:
            package_version = version(package_name)
        except PackageNotFoundError:
            return None
        return package_version

    def _scheme(self) -> str:
        """
        Pick the URL scheme that --https selects.

        :return: "https" when --https is set, else "http"
        """
        scheme: str = "http"
        if self.args.https:
            scheme = "https"
        return scheme
