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

from http import HTTPStatus
from io import BytesIO
from logging import Logger
from logging import getLogger
from pathlib import Path
from urllib.parse import ParseResult
from urllib.parse import urlparse
from urllib.parse import urlsplit
from urllib.request import url2pathname

from aiohttp import ClientSession
from aiofiles import open as async_open
from typing_extensions import override

from leaf_common.logging.sensitive_logger import SensitiveLogger
from leaf_common.serialization.interface.serialization_format import SerializationFormat

from neuro_san.internals.graph.persistence.agent_network_on_boarding import AgentNetworkOnBoarding
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.interfaces.agent_network_provider import AgentNetworkProvider
from neuro_san.internals.network_providers.agent_network_storage import AgentNetworkStorage
from neuro_san.internals.utils.external_agent_parsing import ExternalAgentParsing
from neuro_san.internals.utils.neuro_san_config import NeuroSanConfig
from neuro_san.message.utils.decode_utils import DecodeUtils


class FetchedAgentNetworkStorage(AgentNetworkStorage):
    """
    AgentNetworkStorage implementation where AgentNetworks' names are full URLs
    and their contents are fetched from the network or a local file.
    Only URLs whose scheme is listed in the AGENT_FETCHABLE_TOOL_SCHEMES
    environment variable are fetched.
    """

    # The url schemes that AGENT_FETCHABLE_TOOL_SCHEMES may enable.
    # A bare path counts as "file".
    SUPPORTED_SCHEMES: List[str] = ["http", "https", "file"]

    def __init__(self, fetchable_schemes: List[str] = None):
        """
        Constructor

        :param fetchable_schemes: The url schemes allowed for fetching.
                    Default of None reads them from the AGENT_FETCHABLE_TOOL_SCHEMES environment variable.
        """
        super().__init__()

        self.sensitive_logger: SensitiveLogger = SensitiveLogger(self.logger)

        self.fetchable_schemes: List[str] = fetchable_schemes
        if self.fetchable_schemes is None:
            self.fetchable_schemes = self.get_fetchable_schemes()

        self.extension_to_serialization_format: Dict[str, SerializationFormat] = {}

        # Populate the dictionary from the list of SerializationFormats.
        one_format: SerializationFormat = None
        for one_format in ExternalAgentParsing.AGENT_NETWORK_SERIALIZATION_FORMATS:
            # The file extension already includes the leading dot.
            file_extension: str = one_format.get_file_extension()
            self.extension_to_serialization_format[file_extension] = one_format

    @override
    async def async_get_agent_network_provider(self, agent_name: str) -> AgentNetworkProvider:
        """
        Get AgentNetworkProvider for a specific agent

        :param agent_name: name of an agent which in this case is a full URL
        :return: an AgentNetworkProvider corresponding to the contents of the URL or
                None if the scheme is not fetchable, or the file was not found or had the wrong suffix.
        """
        # Use the synchronous version on the super class to maybe return what was already cached.
        # The provider itself is never None, so check its network.
        network_provider: AgentNetworkProvider = super().get_agent_network_provider(agent_name)
        agent_network: AgentNetwork = network_provider.get_agent_network()
        if agent_network is not None:
            return network_provider

        # See if fetching is allowed for the scheme and we support the serialization format
        suffix: str = self.get_fetchable_suffix(agent_name)
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

        # DEF: Unclear how to get correct external_network_names and mcp_servers in here.
        on_boarding: AgentNetworkOnBoarding = AgentNetworkOnBoarding(agent_name, True)

        # Create the AgentNetwork and have it go through on-boarding.
        # A URL does not map to a package under AGENT_TOOL_PATH,
        # so CodedTool class references must be fully-qualified.
        agent_network = on_boarding.on_board(agent_spec)
        if agent_network is None:
            return None

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
        scheme: str = parse_result.scheme
        url: str = parse_result.geturl()
        contents: str = None

        # For now, no retries
        try:
            if scheme == "file":
                # A file URL is percent-encoded, so decode it to a local path.
                contents = await self.fetch_local_file(url2pathname(parse_result.path))
            elif len(scheme) <= 1:
                # No scheme is a plain path, used literally.
                # A one-letter scheme is a Windows drive letter, as in C:\nets\a.hocon.
                contents = await self.fetch_local_file(agent_name)
            else:
                contents = await self.fetch_over_network(url)
        # pylint: disable=broad-except
        except Exception as exception:
            self.sensitive_logger.warning("Failed to fetch agent network file %s: %s", url, str(exception))
            return None

        return contents

    def get_fetchable_suffix(self, agent_name: str) -> str:
        """
        Get the supported suffix of an agent network whose url scheme allows fetching

        :param agent_name: name of an agent which in this case is a full URL
        :return: the supported suffix, or None if no supported suffix is found
                or the scheme is not in the fetchable schemes.
        """
        # Check the suffix first, so that references which are not network files,
        # such as remote agents, do not log the scheme message below.
        suffix: str = self.get_supported_suffix(agent_name)
        if suffix is None:
            return None

        scheme: str = self.get_fetch_scheme(agent_name)
        if scheme not in self.fetchable_schemes:
            self.sensitive_logger.info("Not fetching %s: scheme '%s' is not in AGENT_FETCHABLE_TOOL_SCHEMES %s",
                                       agent_name, scheme, self.fetchable_schemes)
            return None

        return suffix

    @staticmethod
    def get_fetch_scheme(agent_name: str) -> str:
        """
        Get the url scheme that governs whether an agent network may be fetched

        :param agent_name: name of an agent which in this case is a full URL
        :return: the lower-cased url scheme, where a bare path counts as "file"
        """
        scheme: str = urlparse(agent_name).scheme.lower()

        # No scheme is a plain path, and a one-letter scheme is a Windows drive letter.
        # Both are read from the local filesystem, as fetch_contents() does.
        if len(scheme) <= 1:
            scheme = "file"

        return scheme

    @staticmethod
    def get_fetchable_schemes() -> List[str]:
        """
        Get the url schemes allowed for fetching from the AGENT_FETCHABLE_TOOL_SCHEMES environment variable.
        Schemes are separated by commas and/or whitespace. Unsupported schemes are logged and ignored.

        :return: the list of lower-cased url schemes allowed for fetching.
                An empty list means that nothing is fetched.
        """
        value: str = NeuroSanConfig.get("internals.tools.AGENT_FETCHABLE_TOOL_SCHEMES")

        fetchable_schemes: List[str] = []
        one_scheme: str = None
        # Commas and whitespace both separate entries.
        space_delimited: str = value.replace(",", " ")
        schemes: List[str] = space_delimited.split()
        for one_scheme in schemes:
            lower_scheme: str = one_scheme.lower()
            if lower_scheme not in FetchedAgentNetworkStorage.SUPPORTED_SCHEMES:
                logger: Logger = getLogger(FetchedAgentNetworkStorage.__name__)
                logger.warning("Ignoring unsupported scheme '%s' in AGENT_FETCHABLE_TOOL_SCHEMES. Supported: %s",
                               one_scheme, FetchedAgentNetworkStorage.SUPPORTED_SCHEMES)
                continue
            if lower_scheme not in fetchable_schemes:
                fetchable_schemes.append(lower_scheme)

        return fetchable_schemes

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

        # Caller should have already taken care of any "file://" scheme.
        async with async_open(url, "rb") as file_obj:
            my_bytes: bytes = await file_obj.read()
            contents = DecodeUtils.decode(my_bytes)

        return contents

    async def fetch_over_network(self, url: str) -> str:
        """
        Fetch the contents of an agent network over the network.

        :param url: The location of an agent network description
        :return: the contents of the agent network file
        :raises ValueError: if the server responds with a redirect
        """
        # Collect raw bytes and decode once, so multibyte characters split across chunks stay intact.
        stream: BytesIO = BytesIO()
        async with ClientSession() as session:
            # Do not follow redirects, so a server cannot steer the fetch to a location other than the one requested.
            async with session.get(url, allow_redirects=False) as response:
                if HTTPStatus.MULTIPLE_CHOICES <= response.status < HTTPStatus.BAD_REQUEST:
                    location: str = response.headers.get("Location")
                    raise ValueError(f"Refusing redirect ({response.status}) from {url} to {location}")
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
        :param url: The location of an agent network description
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
