
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

import os

from neuro_san.internals.run_context.langchain.llms.langchain_llm_client import LangChainLlmClient


class LangChainLlmClientFactory:
    """
    Interface for Factory classes creating LLM client connections for LangChain.
    """

    def create_llm_client(self, config: Dict[str, Any]) -> LangChainLlmClient:
        """
        Create a LangChainLlmClient instance from the fully-specified llm config.
        :param config: The fully specified llm config
        :return: A LangChainLlmClient instance containing run-time resources necessary
                for model usage by the service.

                Can raise a ValueError if the config's class or model_name value is
                unknown to this method.
        """
        raise NotImplementedError

    def get_value_or_env(self, config: Dict[str, Any], key: str, env_key: str) -> Any:
        """
        :param config: The config dictionary to search
        :param key: The key for the config to look for
        :param env_key: The os.environ key whose value should be gotten if either
                        the key does not exist or the value for the key is None
        """
        value = None
        if config is not None:
            value = config.get(key)

        if value is None:
            value = os.getenv(env_key)

        return value
