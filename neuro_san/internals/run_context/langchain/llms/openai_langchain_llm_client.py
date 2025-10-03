
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
from typing import Any
from typing import Dict

from contextlib import suppress
from httpx import AsyncClient

from langchain_core.language_models.base import BaseLanguageModel

from leaf_common.config.resolver import Resolver

from neuro_san.internals.run_context.langchain.llms.langchain_llm_client import LangChainLlmClient


class OpenAILangChainLlmClient(LangChainLlmClient):
    """
    LangChainLlmClient implementation for OpenAI.

    OpenAI's BaseLanguageModel implementations do allow us to pass in a web client
    as an argument, so this implementation takes advantage of the create_client()
    method to do that. Worth noting that where many other implementations might care about
    the llm reference, because of our create_client() implementation, we do not.
    """

    def __init__(self, llm: BaseLanguageModel = None):
        """
        Constructor.
        """
        super().__init__()

        self.http_client: AsyncClient = None

        # Not doing lazy type resolution here just for type hints.
        # Save that for create_client(), where it's meatier.
        self.async_openai_client: Any = None

    def create_client(self, config: Dict[str, Any]) -> Any:
        """
        Creates the web client to used by a BaseLanguageModel to be
        constructed in the future.  Neuro SAN infrastructures prefers that this
        be an asynchronous client, however we realize some BaseLanguageModels
        do not support that (even though they should!).

        Implementations should retain any references to state that needs to be cleaned up
        in the delete_resources() method.

        :param config: The fully specified llm config
        :return: The web client that accesses the LLM.
                By default this is None, as many BaseLanguageModels
                do not allow a web client to be passed in as an arg.
        """
        # OpenAI is the one chat class that we do not require any extra installs.
        # This is what we want to work out of the box.
        # Nevertheless, have it go through the same lazy-loading resolver rigamarole as the others.

        # Set up a resolver to use to resolve lazy imports of classes from
        # langchain_* packages to prevent installing the world.
        resolver = Resolver()

        # pylint: disable=invalid-name
        AsyncOpenAI = resolver.resolve_class_in_module("AsyncOpenAI",
                                                       module_name="openai",
                                                       install_if_missing="langchain-openai")

        self.create_http_client(config)

        self.async_openai_client = AsyncOpenAI(
            api_key=self.get_value_or_env(config, "openai_api_key", "OPENAI_API_KEY"),
            base_url=self.get_value_or_env(config, "openai_api_base", "OPENAI_API_BASE"),
            organization=self.get_value_or_env(config, "openai_organization", "OPENAI_ORG_ID"),
            timeout=config.get("request_timeout"),
            max_retries=config.get("max_retries"),
            http_client=self.http_client
        )

        # We retain the async_openai_client reference, but we hand back this reach-in
        # to pass to the BaseLanguageModel constructor.
        return self.async_openai_client.chat.completions

    def create_http_client(self, config: Dict[str, Any]):
        """
        Creates the http client from the given config.

        :param config: The fully specified llm config
        """
        # Our run-time model resource here is httpx client which we need to control directly:
        openai_proxy: str = self.get_value_or_env(config, "openai_proxy", "OPENAI_PROXY")
        request_timeout: int = config.get("request_timeout")
        self.http_client = AsyncClient(proxy=openai_proxy, timeout=request_timeout)

    async def delete_resources(self):
        """
        Release the run-time resources used by the instance.
        """
        self.async_openai_client = None

        if self.http_client is not None:
            with suppress(Exception):
                await self.http_client.aclose()

        self.http_client = None
