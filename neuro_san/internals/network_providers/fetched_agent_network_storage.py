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

from io import BytesIO
from pathlib import Path
from urllib.parse import ParseResult
from urllib.parse import urlparse
from urllib.parse import urlsplit

from aiohttp import ClientSession
from aiofiles import open as async_open
from typing_extensions import override

from leaf_common.logging.sensitive_logger import SensitiveLogger
from leaf_common.serialization.interface.serialization_format import SerializationFormat
from leaf_common.serialization.format.json_serialization_format import JsonSerializationFormat
from leaf_common.serialization.format.hocon_serialization_format import HoconSerializationFormat

from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.interfaces.agent_network_provider import AgentNetworkProvider
from neuro_san.internals.network_providers.agent_network_storage import AgentNetworkStorage
from neuro_san.message.utils.decode_utils import DecodeUtils


class FetchedAgentNetworkStorage(AgentNetworkStorage):
    """
    AgentNetworkStorage implementation where AgentNetworks' names are full URLs
    and their contents are fetched from the network or a local file.
    """

    def __init__(self):
        """
        Constructor
        """
        super().__init__()

        self.sensitive_logger: SensitiveLogger = SensitiveLogger(self.logger)
        self.extension_to_serialization_format: Dict[str, SerializationFormat] = {}

        format_list: List[SerializationFormat] = [
            JsonSerializationFormat(),
            HoconSerializationFormat(),
        ]

        # Populate the dictionary from the list of SerializationFormats.
        one_format: SerializationFormat = None
        for one_format in format_list:
            # The file extension already includes the leading dot.
            file_extension: str = one_format.get_file_extension()
            self.extension_to_serialization_format[file_extension] = one_format

    @override
    async def async_get_agent_network_provider(self, agent_name: str) -> AgentNetworkProvider:
        """
        Get AgentNetworkProvider for a specific agent

        :param agent_name: name of an agent which in this case is a full URL
        :return: an AgentNetworkProvider corresponding to the contents of the URL or
                None if the file was not found or had the wrong suffix.
        """
        # Use the synchronous version on the super class to maybe return what was already cached.
        # The provider itself is never None, so check its network.
        network_provider: AgentNetworkProvider = super().get_agent_network_provider(agent_name)
        agent_network: AgentNetwork = network_provider.get_agent_network()
        if agent_network is not None:
            return network_provider

        # See if we support the serialization format
        suffix: str = self.get_supported_suffix(agent_name)
        if suffix is None:
            return None

        # Fetch the contents of the file
        contents: str = await self.fetch_contents(agent_name)
        if contents is None:
            return None

        # Parse the contents of the file into a dictionary
        agent_spec: Dict[str, Any] = self.parse_contents(contents, suffix, agent_name)
        if agent_spec is None:
            return None

        # DEF: Validate spec?
        agent_network = AgentNetwork(agent_spec, agent_name)

        # Add the AgentNetwork to the cache
        # Note: Synchronous lock inside
        self.add_agent_network(agent_name, agent_network)

        # Return the provider, as the method signature requires
        network_provider = super().get_agent_network_provider(agent_name)
        return network_provider

    async def fetch_contents(self, agent_name: str) -> str:
        """
        Fetch the contents of an agent network

        :param agent_name: name of an agent which in this case is a full URL
        :return: the contents of the agent network file
        """
        parse_result: ParseResult = urlparse(agent_name)
        scheme: str = parse_result.scheme or "file"
        url: str = parse_result.geturl()
        contents: str = None

        # For now, no retries
        try:
            if scheme == "file":
                contents = await self.fetch_local_file(parse_result.path)
            else:
                contents = await self.fetch_over_network(url)
        # pylint: disable=broad-except
        except Exception as exception:
            self.sensitive_logger.warning("Failed to fetch agent network file %s: %s", url, str(exception))
            return None

        return contents

    def get_supported_suffix(self, agent_name: str) -> str:
        """
        :param agent_name: name of an agent
        :return: the supported suffix or None if no supported suffix is found.
        """
        clean_path: str = urlsplit(agent_name).path
        file_extension: str = Path(clean_path).suffix

        suffix: str = None
        found_suffix: bool = False
        suffixes: List[str] = list(self.extension_to_serialization_format.keys())
        for suffix in suffixes:
            if file_extension.endswith(suffix):
                found_suffix = True
                break

        if found_suffix:
            return suffix

        return None

    async def fetch_local_file(self, url: str) -> str:
        """
        Fetch the contents of an agent network from a local file

        :param url: The location of an agent network description
        :return: the contents of the agent network file
        """
        contents: str = None

        # DEF: strip "file://"?
        async with async_open(url, "r") as file_obj:
            contents = await file_obj.read()

        return contents

    async def fetch_over_network(self, url: str) -> str:
        """
        Fetch the contents of an agent network over the network.

        :param url: The location of an agent network description
        :return: the contents of the agent network file
        """
        # Collect raw bytes and decode once, so multibyte characters split across chunks stay intact.
        stream: BytesIO = BytesIO()
        async with ClientSession() as session:
            async with session.get(url) as response:
                response.raise_for_status()
                chunk: bytes = None
                async for chunk in response.content.iter_chunked(1024):
                    stream.write(chunk)

        my_bytes: bytes = stream.getvalue()
        contents: str = DecodeUtils.decode(my_bytes)
        return contents

    def parse_contents(self, contents: str, suffix: str, url: str) -> Dict[str, Any]:
        """
        Parse the contents of an agent network file

        :param contents: The contents of an agent network file
        :param suffix: The suffix of the file
        :return: the contents of the agent network file
        """
        serialization_format: SerializationFormat = self.extension_to_serialization_format.get(suffix)
        if serialization_format is None:
            return None

        # SerializationFormat requires a bytes stream.
        my_bytes: bytes = contents.encode("utf-8")
        stream: BytesIO = BytesIO(my_bytes)
        agent_spec: Dict[str, Any] = None
        try:
            agent_spec = serialization_format.to_object(stream)
        # pylint: disable=broad-except
        except Exception as exception:
            self.sensitive_logger.warning("Failed to parse agent network file: %s, %s", url, str(exception))
            return None

        return agent_spec
