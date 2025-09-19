
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

from langchain_core.language_models.base import BaseLanguageModel

from neuro_san.internals.run_context.langchain.llms.langchain_llm_client import LangChainLlmClient


class LangChainLlmResources:
    """
    Class for representing a LangChain model
    together with run-time resources necessary for model usage by the service.
    """

    def __init__(self, model: BaseLanguageModel, llm_client: LangChainLlmClient = None):
        """
        Constructor.
        :param model: Language model used.
        :param http_client: optional httpx.AsyncClient used for model connections to LLM host.
        """
        self.model: BaseLanguageModel = model
        self.llm_client: LangChainLlmClient = llm_client

    def get_model(self) -> BaseLanguageModel:
        """
        Get the language model
        """
        return self.model

    def get_llm_client(self) -> LangChainLlmClient:
        """
        Get the client used by the model
        """
        return self.llm_client

    async def delete_resources(self):
        """
        Release the run-time resources used by the model
        """
        if self.llm_client:
            await self.llm_client.delete_resources()
