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
from typing import Type

from langchain_core.language_models.base import BaseLanguageModel

from neuro_san.internals.run_context.langchain.llms.anthropic_llm_policy import AnthropicLlmPolicy
from neuro_san.internals.run_context.langchain.llms.azure_llm_policy import AzureLlmPolicy
from neuro_san.internals.run_context.langchain.llms.bedrock_llm_policy import BedrockLlmPolicy
from neuro_san.internals.run_context.langchain.llms.gemini_llm_policy import GeminiLlmPolicy
from neuro_san.internals.run_context.langchain.llms.llm_policy import LlmPolicy
from neuro_san.internals.run_context.langchain.llms.langchain_llm_factory import LangChainLlmFactory
from neuro_san.internals.run_context.langchain.llms.langchain_llm_resources import LangChainLlmResources
from neuro_san.internals.run_context.langchain.llms.nvidia_llm_policy import NvidiaLlmPolicy
from neuro_san.internals.run_context.langchain.llms.ollama_llm_policy import OllamaLlmPolicy
from neuro_san.internals.run_context.langchain.llms.openai_llm_policy import OpenAILlmPolicy


class StandardLangChainLlmFactory(LangChainLlmFactory):
    """
    Factory class for LLM operations

    Most methods take a config dictionary which consists of the following keys:

        "model_name"                The name of the model.
                                    Default if not specified is "gpt-3.5-turbo"

        "temperature"               A float "temperature" value with which to
                                    initialize the chat model.  In general,
                                    higher temperatures yield more random results.
                                    Default if not specified is 0.7

        "max_tokens"                The maximum number of tokens to use in
                                    get_max_prompt_tokens(). By default, this comes from
                                    the model description in this class.
    """

    def __init__(self):
        """
        Constructor
        """
        self.policy_name_to_class: Dict[str, LlmPolicy] = {
            "anthropic": AnthropicLlmPolicy,
            "azure-openai": AzureLlmPolicy,
            "bedrock": BedrockLlmPolicy,
            "gemini": GeminiLlmPolicy,
            "nvidia": NvidiaLlmPolicy,
            "openai": OpenAILlmPolicy,
            "ollama": OllamaLlmPolicy,
        }

    def create_base_chat_model(self, config: Dict[str, Any]) -> BaseLanguageModel:
        """
        Create a BaseLanguageModel from the fully-specified llm config.

        This method is provided for backwards compatibility.
        Prefer create_llm_resources() instead,
        as this allows server infrastructure to better account for outstanding
        connections to LLM providers when connections drop.

        :param config: The fully specified llm config which is a product of
                    _create_full_llm_config() above.
        :return: A BaseLanguageModel (can be Chat or LLM)
                Can raise a ValueError if the config's class or model_name value is
                unknown to this method.
        """
        raise NotImplementedError

    # pylint: disable=too-many-branches
    def create_llm_resources(self, config: Dict[str, Any]) -> LangChainLlmResources:
        """
        Create a BaseLanguageModel from the fully-specified llm config.
        :param config: The fully specified llm config which is a product of
                    _create_full_llm_config() above.
        :return: A LangChainLlmResources instance containing
                a BaseLanguageModel (can be Chat or LLM) and all related resources
                necessary for managing the model run-time lifecycle.
                Can raise a ValueError if the config's class or model_name value is
                unknown to this method.
        """
        # pylint: disable=too-many-locals
        # Construct the LLM
        llm: BaseLanguageModel = None

        chat_class: str = config.get("class")
        if chat_class is not None:
            chat_class = chat_class.lower()

        # Check for key "model_name", "model", and "model_id" to use as model name
        # If the config is from default_llm_info, this is always "model_name"
        # but with user-specified config, it is possible to have the other keys will be specifed instead.
        model_name: str = config.get("model_name") or config.get("model") or config.get("model_id")

        # Get from table of policy classes
        llm_policy: LlmPolicy = None
        policy_class: Type[LlmPolicy] = self.policy_name_to_class.get(chat_class)
        if policy_class is not None:

            # Use the LlmPolicy type we found in the lookup table to create an call a new instance.
            llm_policy = policy_class()
            llm, llm_policy = llm_policy.create_llm_resources_components(config)

        elif chat_class is None:
            raise ValueError(f"Class name {chat_class} for model_name {model_name} is unspecified.")
        else:
            raise ValueError(f"Class {chat_class} for model_name {model_name} is unrecognized.")

        # Return the LlmResources with the llm_policy that was created.
        # That might be None, and that's OK.
        return LangChainLlmResources(llm, llm_policy=llm_policy)
