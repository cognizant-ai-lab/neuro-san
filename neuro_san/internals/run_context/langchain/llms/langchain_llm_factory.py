
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

from langchain_core.language_models.base import BaseLanguageModel

from neuro_san.internals.run_context.langchain.llms.langchain_llm_client import LangChainLlmClient
from neuro_san.internals.run_context.langchain.llms.langchain_llm_resources import LangChainLlmResources


class LangChainLlmFactory:
    """
    Interface for Factory classes creating LLM BaseLanguageModels

    Most methods take a config dictionary which consists of the following keys:

        "model_name"                The name of the model.
                                    Default if not specified is "gpt-3.5-turbo"

        "temperature"               A float "temperature" value with which to
                                    initialize the chat model.  In general,
                                    higher temperatures yield more random results.
                                    Default if not specified is 0.7

        "prompt_token_fraction"     The fraction of total tokens (not necessarily words
                                    or letters) to use for a prompt. Each model_name
                                    has a documented number of max_tokens it can handle
                                    which is a total count of message + response tokens
                                    which goes into the calculation involved in
                                    get_max_prompt_tokens().
                                    By default the value is 0.5.

        "max_tokens"                The maximum number of tokens to use in
                                    get_max_prompt_tokens(). By default this comes from
                                    the model description in this class.
    """

    def create_base_chat_model(self, config: Dict[str, Any]) -> BaseLanguageModel:
        """
        Create a LangChainLlmResources instance from the fully-specified llm config.
        :param config: The fully specified llm config which is a product of
                    _create_full_llm_config() above.
        :return: A BaseLanguageModel (can be Chat or LLM)
                Can raise a ValueError if the config's class or model_name value is
                unknown to this method.
        """
        raise NotImplementedError

    def create_llm_resources_with_client(self, config: Dict[str, Any],
                                         llm_client: LangChainLlmClient = None) -> LangChainLlmResources:
        """
        Create a LangChainLlmResources instance from the fully-specified llm config.

        :param config: The fully specified llm config which is a product of
                    _create_full_llm_config() above.
        :param llm_client: A LangChainLlmClient instance, which by default is None,
                        implying that create_base_chat_model() needs to create its own client.
                        Note, however that a None value can lead to connection leaks and requests
                        that continue to run after the request connection is dropped in a server
                        environment.
        :return: A LangChainLlmResources instance containing
                a BaseLanguageModel (can be Chat or LLM) and all related resources
                necessary for managing the model run-time lifecycle.
                Can raise a ValueError if the config's class or model_name value is
                unknown to this method.
        """
        raise NotImplementedError

    def get_value_or_env(self, config: Dict[str, Any], key: str, env_key: str,
                         llm_client: LangChainLlmClient = None) -> Any:
        """
        :param config: The config dictionary to search
        :param key: The key for the config to look for
        :param env_key: The os.environ key whose value should be gotten if either
                        the key does not exist or the value for the key is None
        :param llm_client: A LangChainLlmClient instance.
                        If present this method will return None.
        """
        if llm_client is not None:
            return None

        value = None
        if config is not None:
            value = config.get(key)

        if value is None and env_key is not None:
            value = os.getenv(env_key)

        return value
