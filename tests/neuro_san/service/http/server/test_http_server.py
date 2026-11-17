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
import os

from typing import Any

from unittest import TestCase
from unittest.mock import MagicMock
from unittest.mock import patch

from typing_extensions import override

from neuro_san.internals.utils.neuro_san_config import NeuroSanConfig
from neuro_san.service.http.config.http_server_config import HttpServerConfig
from neuro_san.service.http.server.http_server import HttpServer


class TestHttpServer(TestCase):
    """
    Unit tests for HttpServer.
    """

    @override
    def setUp(self) -> None:
        """
        Isolates the environment for each test and reloads NeuroSanConfig once it is restored.
        """
        # Cleanups run last-in first-out, so this reload sees the restored environment.
        self.addCleanup(NeuroSanConfig.reset_for_testing)
        env_patcher: Any = patch.dict(os.environ)
        env_patcher.start()
        self.addCleanup(env_patcher.stop)
        os.environ.pop("AGENT_HEALTH_PROBE_PORT", None)
        NeuroSanConfig.reset_for_testing()

    @staticmethod
    def make_server(http_probe_port: int) -> HttpServer:
        """
        Builds an HttpServer around a mock ServerContext, without starting it.
        HttpLogger is mocked so that the test does not reconfigure process-wide logging.

        :param http_probe_port: The probe port to put in the HttpServerConfig
        :return: The HttpServer
        """
        server_context: MagicMock = MagicMock()
        server_context.get_network_storage_dict.return_value = {}
        server_config: HttpServerConfig = HttpServerConfig()
        server_config.http_probe_port = http_probe_port
        with patch("neuro_san.service.http.server.http_server.HttpLogger"):
            server: HttpServer = HttpServer(server_context, server_config, openapi_service_spec_path="",
                                            requests_limit=-1, concurrent_requests_limit=0, logging_config={})
        return server

    def test_probe_port_unset_env_uses_server_config(self) -> None:
        """
        With AGENT_HEALTH_PROBE_PORT unset, the probe port comes from HttpServerConfig,
        including 0 to disable the probe server.
        """
        self.assertEqual(9091, self.make_server(9091).resolve_health_probe_port())
        self.assertEqual(0, self.make_server(0).resolve_health_probe_port())

    def test_probe_port_env_overrides_server_config(self) -> None:
        """
        A numeric AGENT_HEALTH_PROBE_PORT wins over HttpServerConfig, and a negative value disables.
        """
        os.environ["AGENT_HEALTH_PROBE_PORT"] = "7071"
        self.assertEqual(7071, self.make_server(9091).resolve_health_probe_port())

        os.environ["AGENT_HEALTH_PROBE_PORT"] = "-1"
        self.assertEqual(0, self.make_server(9091).resolve_health_probe_port())

    def test_probe_port_invalid_env_uses_server_config(self) -> None:
        """
        A non-numeric or empty AGENT_HEALTH_PROBE_PORT falls back to HttpServerConfig.
        """
        os.environ["AGENT_HEALTH_PROBE_PORT"] = "not_a_port"
        self.assertEqual(9091, self.make_server(9091).resolve_health_probe_port())

        os.environ["AGENT_HEALTH_PROBE_PORT"] = ""
        self.assertEqual(9091, self.make_server(9091).resolve_health_probe_port())
