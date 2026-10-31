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

import os
from pathlib import Path
from shutil import rmtree
from tempfile import mkdtemp
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock

from aiohttp import web
from aiohttp.test_utils import TestServer

from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.interfaces.agent_network_provider import AgentNetworkProvider
from neuro_san.internals.network_providers.fetched_agent_network_storage import FetchedAgentNetworkStorage

from tests.neuro_san.internals.network_providers.recording_listener import RecordingListener


# pylint: disable=too-many-public-methods
class TestFetchedAgentNetworkStorage(IsolatedAsyncioTestCase):
    """
    Unit tests for FetchedAgentNetworkStorage: suffix detection, parsing,
    fetching from local files and http, and provider caching.
    """

    HOCON_CONTENTS: str = """
{
    "tools": [
        {
            "name": "announcer",
            "function": {
                "description": "Announces things"
            },
            "instructions": "Announce."
        }
    ]
}
"""

    JSON_CONTENTS: str = '{"tools": [{"name": "greeter", "instructions": "Greet."}]}'

    MALFORMED_CONTENTS: str = '{"tools": [ '

    def setUp(self):
        """
        Create a temporary directory and a fresh storage for each test.
        """
        self.temp_dir: str = mkdtemp()
        self.storage: FetchedAgentNetworkStorage = FetchedAgentNetworkStorage()

    def tearDown(self):
        """
        Remove the temporary directory.
        """
        rmtree(self.temp_dir)

    async def asyncSetUp(self):
        """
        Start a local http server that serves agent network files.
        """
        app: web.Application = web.Application()
        app.router.add_get("/networks/announcer.hocon", self.serve_hocon)
        app.router.add_get("/networks/greeter.json", self.serve_json)
        self.server: TestServer = TestServer(app)
        await self.server.start_server()

    async def asyncTearDown(self):
        """
        Stop the local http server.
        """
        await self.server.close()

    @staticmethod
    async def serve_hocon(request: web.Request) -> web.Response:
        """
        Serve the HOCON agent network.

        :param request: The incoming http request
        :return: A response with the HOCON contents
        """
        _ = request
        return web.Response(text=TestFetchedAgentNetworkStorage.HOCON_CONTENTS)

    @staticmethod
    async def serve_json(request: web.Request) -> web.Response:
        """
        Serve the JSON agent network.

        :param request: The incoming http request
        :return: A response with the JSON contents
        """
        _ = request
        return web.Response(text=TestFetchedAgentNetworkStorage.JSON_CONTENTS)

    def write_file(self, file_name: str, contents: str) -> str:
        """
        Write a file into the temporary directory.

        :param file_name: The name of the file to write
        :param contents: The contents to write
        :return: The full path of the file written
        """
        path: str = os.path.join(self.temp_dir, file_name)
        with open(path, "w", encoding="utf-8") as file_obj:
            file_obj.write(contents)
        return path

    def server_url(self, path: str) -> str:
        """
        :param path: The path on the local http server
        :return: The full http URL for the path
        """
        return str(self.server.make_url(path))

    def test_extension_keys(self):
        """
        Tests that the extension table is keyed by single-dot extensions.
        """
        keys: List[str] = list(self.storage.extension_to_serialization_format.keys())
        self.assertCountEqual([".json", ".hocon"], keys)

    def test_get_supported_suffix_hocon(self):
        """
        Tests that a .hocon path is supported.
        """
        self.assertEqual(".hocon", self.storage.get_supported_suffix("/some/dir/network.hocon"))

    def test_get_supported_suffix_json(self):
        """
        Tests that a .json path is supported.
        """
        self.assertEqual(".json", self.storage.get_supported_suffix("/some/dir/network.json"))

    def test_get_supported_suffix_url_with_query(self):
        """
        Tests that the query string and fragment of a URL are ignored.
        """
        agent_name: str = "https://example.com/networks/network.hocon?version=2#top"
        self.assertEqual(".hocon", self.storage.get_supported_suffix(agent_name))

    def test_get_supported_suffix_unsupported(self):
        """
        Tests that an unsupported extension returns None.
        """
        self.assertIsNone(self.storage.get_supported_suffix("/some/dir/network.txt"))

    def test_get_supported_suffix_no_extension(self):
        """
        Tests that a path without an extension returns None.
        """
        self.assertIsNone(self.storage.get_supported_suffix("https://example.com/networks/network"))

    def test_parse_contents_hocon(self):
        """
        Tests parsing valid HOCON contents.
        """
        agent_spec: Dict[str, Any] = self.storage.parse_contents(self.HOCON_CONTENTS, ".hocon", "x.hocon")
        self.assertIsNotNone(agent_spec)
        self.assertEqual("announcer", agent_spec.get("tools")[0].get("name"))

    def test_parse_contents_json(self):
        """
        Tests parsing valid JSON contents.
        """
        agent_spec: Dict[str, Any] = self.storage.parse_contents(self.JSON_CONTENTS, ".json", "x.json")
        self.assertIsNotNone(agent_spec)
        self.assertEqual("greeter", agent_spec.get("tools")[0].get("name"))

    def test_parse_contents_malformed_json(self):
        """
        Tests that malformed JSON returns None rather than raising.
        """
        self.assertIsNone(self.storage.parse_contents(self.MALFORMED_CONTENTS, ".json", "x.json"))

    def test_parse_contents_malformed_hocon(self):
        """
        Tests that malformed HOCON returns None rather than raising.
        """
        self.assertIsNone(self.storage.parse_contents(self.MALFORMED_CONTENTS, ".hocon", "x.hocon"))

    def test_parse_contents_unknown_suffix(self):
        """
        Tests that an unknown suffix returns None.
        """
        self.assertIsNone(self.storage.parse_contents(self.JSON_CONTENTS, ".txt", "x.txt"))

    async def test_fetch_local_file(self):
        """
        Tests reading a local file by plain path.
        """
        path: str = self.write_file("network.hocon", self.HOCON_CONTENTS)
        contents: str = await self.storage.fetch_local_file(path)
        self.assertEqual(self.HOCON_CONTENTS, contents)

    async def test_fetch_contents_plain_path(self):
        """
        Tests fetching a plain local path, which has no URL scheme.
        """
        path: str = self.write_file("network.hocon", self.HOCON_CONTENTS)
        contents: str = await self.storage.fetch_contents(path)
        self.assertEqual(self.HOCON_CONTENTS, contents)

    async def test_fetch_contents_file_url(self):
        """
        Tests fetching a local file given as a file:// URL.
        """
        path: str = self.write_file("network.hocon", self.HOCON_CONTENTS)
        contents: str = await self.storage.fetch_contents(Path(path).as_uri())
        self.assertEqual(self.HOCON_CONTENTS, contents)

    async def test_fetch_contents_missing_file(self):
        """
        Tests that a missing local file returns None rather than raising.
        """
        path: str = os.path.join(self.temp_dir, "missing.hocon")
        self.assertIsNone(await self.storage.fetch_contents(path))

    async def test_fetch_over_network(self):
        """
        Tests fetching contents from an http server.
        """
        contents: str = await self.storage.fetch_over_network(self.server_url("/networks/greeter.json"))
        self.assertEqual(self.JSON_CONTENTS, contents)

    async def test_fetch_contents_http(self):
        """
        Tests that fetch_contents() dispatches an http URL to the network.
        """
        contents: str = await self.storage.fetch_contents(self.server_url("/networks/announcer.hocon"))
        self.assertEqual(self.HOCON_CONTENTS, contents)

    async def test_fetch_contents_http_not_found(self):
        """
        Tests that an http error status returns None rather than raising.
        """
        self.assertIsNone(await self.storage.fetch_contents(self.server_url("/networks/missing.hocon")))

    async def test_get_provider_local_hocon(self):
        """
        Tests getting a provider for a local HOCON file.
        """
        path: str = self.write_file("network.hocon", self.HOCON_CONTENTS)
        provider: AgentNetworkProvider = await self.storage.async_get_agent_network_provider(path)
        self.assertIsNotNone(provider)

        agent_network: AgentNetwork = provider.get_agent_network()
        self.assertIsNotNone(agent_network)
        self.assertEqual("announcer", agent_network.get_config().get("tools")[0].get("name"))
        self.assertIn(path, self.storage.get_agent_names())

    async def test_get_provider_local_json(self):
        """
        Tests getting a provider for a local JSON file.
        """
        path: str = self.write_file("network.json", self.JSON_CONTENTS)
        provider: AgentNetworkProvider = await self.storage.async_get_agent_network_provider(path)
        self.assertIsNotNone(provider)

        agent_network: AgentNetwork = provider.get_agent_network()
        self.assertIsNotNone(agent_network)
        self.assertEqual("greeter", agent_network.get_config().get("tools")[0].get("name"))

    async def test_get_provider_http(self):
        """
        Tests getting a provider for an agent network served over http.
        """
        url: str = self.server_url("/networks/announcer.hocon")
        provider: AgentNetworkProvider = await self.storage.async_get_agent_network_provider(url)
        self.assertIsNotNone(provider)

        agent_network: AgentNetwork = provider.get_agent_network()
        self.assertIsNotNone(agent_network)
        self.assertEqual("announcer", agent_network.get_config().get("tools")[0].get("name"))

    async def test_get_provider_unsupported_suffix(self):
        """
        Tests that an unsupported suffix returns None without fetching.
        """
        path: str = self.write_file("network.txt", self.JSON_CONTENTS)
        self.storage.fetch_contents = AsyncMock(return_value=self.JSON_CONTENTS)

        self.assertIsNone(await self.storage.async_get_agent_network_provider(path))
        self.storage.fetch_contents.assert_not_awaited()

    async def test_get_provider_missing_file(self):
        """
        Tests that a missing file returns None and stores nothing.
        """
        path: str = os.path.join(self.temp_dir, "missing.hocon")
        self.assertIsNone(await self.storage.async_get_agent_network_provider(path))
        self.assertEqual([], self.storage.get_agent_names())

    async def test_get_provider_malformed_file(self):
        """
        Tests that a malformed file returns None and stores nothing.
        """
        path: str = self.write_file("network.json", self.MALFORMED_CONTENTS)
        self.assertIsNone(await self.storage.async_get_agent_network_provider(path))
        self.assertEqual([], self.storage.get_agent_names())

    async def test_get_provider_cached(self):
        """
        Tests that a second request is served from storage without fetching again.
        """
        path: str = self.write_file("network.hocon", self.HOCON_CONTENTS)
        first: AgentNetworkProvider = await self.storage.async_get_agent_network_provider(path)
        self.assertIsNotNone(first)
        first_network: AgentNetwork = first.get_agent_network()
        self.assertIsNotNone(first_network)

        self.storage.fetch_contents = AsyncMock(return_value=None)
        second: AgentNetworkProvider = await self.storage.async_get_agent_network_provider(path)
        self.assertIsNotNone(second)
        self.assertIs(first_network, second.get_agent_network())
        self.storage.fetch_contents.assert_not_awaited()

    async def test_get_provider_notifies_listener(self):
        """
        Tests that listeners hear about a newly fetched agent network.
        """
        listener: RecordingListener = RecordingListener()
        self.storage.add_listener(listener)

        path: str = self.write_file("network.hocon", self.HOCON_CONTENTS)
        await self.storage.async_get_agent_network_provider(path)
        self.assertEqual([path], listener.added)
        self.assertEqual([], listener.modified)
