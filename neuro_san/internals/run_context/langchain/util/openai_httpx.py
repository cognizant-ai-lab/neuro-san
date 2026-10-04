
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
from types import ModuleType
from typing import Any
from typing import Optional

from leaf_common.resolution.resolver import Resolver


class OpenAIHttpx:
    """
    Finds the httpx library the installed OpenAI SDK is built on.

    openai 2.x is built on httpx and openai 3.x on httpx2, a fork with the same API that ships
    under its own import name. A transport, limit or request object handed to the SDK has to
    come from the same library as the SDK's own clients, so code that builds one asks here
    instead of importing either library by name.

    This class only exists while both SDK majors are supported. Once litellm, a common companion
    of neuro-san that still pins openai below 3, and langchain-openai have moved to openai 3, raise
    the openai floor in requirements.txt to 3, import httpx2 directly where this class is used, and
    delete it.
    """

    # Loads third-party modules the way the LLM policies do, installing the SDK when it is missing.
    RESOLVER: Resolver = Resolver()

    @staticmethod
    def module() -> ModuleType:
        """
        Returns the httpx library behind the SDK's own default async client.

        :return: The httpx or httpx2 module
        :raises ValueError: When the SDK's default client has no AsyncClient base to read the library from
        """
        # Resolved here rather than at module load so that the policies keep loading provider SDKs lazily.
        openai_module: ModuleType = OpenAIHttpx.RESOLVER.resolve_class_in_module(class_name=None,
                                                                                 module_name="openai",
                                                                                 install_if_missing="langchain-openai")

        # The SDK's default client is a subclass of the AsyncClient of whichever library the SDK was
        # built on, so its class hierarchy names that library. Walking the hierarchy is more reliable
        # than parsing the SDK version. On openai 2.x it reads
        #     _DefaultAsyncHttpxClient -> httpx.AsyncClient -> httpx._client.BaseClient -> object
        # and on openai 3.x
        #     _DefaultAsyncHttpxClient -> httpx2.AsyncClient -> httpx2._client.BaseClient -> object
        default_client: type = openai_module.DefaultAsyncHttpxClient
        for base in default_client.__mro__:
            if base.__name__ == "AsyncClient":
                # The class's __module__ is the library's import name ("httpx" or "httpx2"), possibly
                # followed by a submodule path; the first component is what gets imported.
                package_name: str = base.__module__.split(".", maxsplit=1)[0]
                return OpenAIHttpx.RESOLVER.resolve_class_in_module(class_name=None, module_name=package_name)
        raise ValueError("openai.DefaultAsyncHttpxClient has no AsyncClient base to read the httpx library from")

    @staticmethod
    def limits(max_connections: Optional[int], max_keepalive_connections: Optional[int]) -> Any:
        """
        Builds connection-pool limits from the SDK's httpx library.

        :param max_connections: The most connections the pool may hold open at once; None means no limit
        :param max_keepalive_connections: The most idle connections the pool may keep; None means no limit
        :return: A Limits instance of the module that module() returns
        """
        return OpenAIHttpx.module().Limits(max_connections=max_connections,
                                           max_keepalive_connections=max_keepalive_connections)
