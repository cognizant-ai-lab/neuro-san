
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
import contextlib
import httpx
from langchain_core.language_models.base import BaseLanguageModel


class LangChainLlmResources:
    """
    Class for representing a LangChain model
    together with run-time resources necessary for model usage by the service.
    """

    def __init__(self, model: BaseLanguageModel, http_client: httpx.AsyncClient = None):
        """
        Constructor.
        :param model: Language model used.
        :param http_client: optional httpx.AsyncClient used for model connections to LLM host.
        """
        self.model = model
        self.http_client = http_client

    def get_model(self) -> BaseLanguageModel:
        """
        Get the language model
        """
        return self.model

    def get_http_client(self) -> httpx.AsyncClient:
        """
        Get the http client used by the model
        """
        return self.http_client

    async def release_resources(self):
        """
        Release the run-time resources used by the model
        """
        if self.http_client:
            with contextlib.suppress(Exception):
                await self.http_client.aclose()
                print("HTTP CLIENT CLOSED<<<<<<<<<<<<<<<<<<")
