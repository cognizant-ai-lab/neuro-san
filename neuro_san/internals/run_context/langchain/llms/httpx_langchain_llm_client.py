
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

from contextlib import suppress
from httpx import AsyncClient

from neuro_san.internals.run_context.langchain.llms.langchain_llm_client import LangChainLlmClient


class HttpxLangChainLlmClient(LangChainLlmClient):
    """
    Implementation of the LangChainLlmClient for httpx clients.
    """

    def __init__(self, http_client: AsyncClient, async_llm_client: Any = None):
        """
        Constructor.

        :param http_client: httpx.AsyncClient used for model connections to LLM host.
        :param async_llm_client: optional async_llm_client used for model connections to LLM host.
                            When used, this is most often ChatModel-specific.
        """
        self.http_client: AsyncClient = http_client
        self.async_llm_client: Any = async_llm_client

    def get_client(self) -> Any:
        """
        Get the async llm client used by the model
        """
        return self.async_llm_client

    async def delete_resources(self):
        """
        Release the run-time resources used by the model
        """
        self.async_llm_client = None

        if self.http_client is None:
            return

        with suppress(Exception):
            await self.http_client.aclose()
        self.http_client = None
