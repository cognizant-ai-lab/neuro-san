
from typing import Any
from typing import Dict

import os

import httpx
from langchain_core.language_models.base import BaseLanguageModel


class LangChainLlmResources:

    def __init__(self, model: BaseLanguageModel, http_client: httpx.AsyncClient):
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
