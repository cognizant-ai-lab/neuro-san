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
from os import environ
from unittest import TestCase
from unittest.mock import patch

from typing_extensions import override

from neuro_san.internals.interfaces.agent_storage_source import AgentStorageSource
from neuro_san.internals.interfaces.storage_class import StorageClass
from neuro_san.internals.utils.neuro_san_config import NeuroSanConfig
from neuro_san.service.utils.server_context import ServerContext


class TestServerContext(TestCase):
    """
    Unit tests for which network storages a ServerContext sets up.
    """

    @override
    def setUp(self) -> None:
        """
        Reloads NeuroSanConfig after each test, once the environment the test changed is restored.
        """
        self.addCleanup(NeuroSanConfig.reset_for_testing)

    def test_no_fetched_storage_by_default(self):
        """
        Tests that there is no fetched storage when AGENT_FETCHABLE_TOOL_SCHEMES is not set.
        """
        with patch.dict(environ, clear=True):
            NeuroSanConfig.reset_for_testing()
            server_context: ServerContext = ServerContext()
        self.assertNotIn(StorageClass.FETCHED, server_context.get_network_storage_dict())
        self.assertIn(StorageClass.TEMP, server_context.get_network_storage_dict())

    def test_no_fetched_storage_for_unsupported_schemes(self):
        """
        Tests that there is no fetched storage when AGENT_FETCHABLE_TOOL_SCHEMES has no supported scheme.
        """
        with patch.dict(environ, {"AGENT_FETCHABLE_TOOL_SCHEMES": "ftp"}):
            NeuroSanConfig.reset_for_testing()
            server_context: ServerContext = ServerContext()
        self.assertNotIn(StorageClass.FETCHED, server_context.get_network_storage_dict())

    def test_fetched_storage_when_enabled(self):
        """
        Tests that there is a fetched storage when AGENT_FETCHABLE_TOOL_SCHEMES enables a scheme.
        """
        with patch.dict(environ, {"AGENT_FETCHABLE_TOOL_SCHEMES": "https,file"}):
            NeuroSanConfig.reset_for_testing()
            server_context: ServerContext = ServerContext()
        fetched_storage: AgentStorageSource = server_context.get_network_storage_dict().get(StorageClass.FETCHED)
        self.assertIsNotNone(fetched_storage)
