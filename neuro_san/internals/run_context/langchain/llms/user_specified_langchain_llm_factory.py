
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
from typing import List

from langchain_anthropic.chat_models import ChatAnthropic
from langchain_google_genai.chat_models import ChatGoogleGenerativeAI
from langchain_ollama import ChatOllama
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.language_models.base import BaseLanguageModel
from langchain_openai.chat_models.azure import AzureChatOpenAI
from langchain_openai.chat_models.base import ChatOpenAI

from neuro_san.internals.run_context.langchain.llms.langchain_llm_factory import LangChainLlmFactory


class UserSpecifiedLangChainLlmFactory(LangChainLlmFactory):
    """
    A factory for constructing LLMs based on user-specified configurations provided under the "llm_config"
    section of the agent network HOCON file.

    The specific LLM class to instantiate is determined by the "class" field in "llm_config", and all
    other keys in the config are passed as arguments to that class's constructor.
    """

    def create_base_chat_model(self, config: Dict[str, Any],
                               callbacks: List[BaseCallbackHandler] = None) -> BaseLanguageModel:
        """
        Create a BaseLanguageModel from the user-specified llm config.
        :param config: The user-specified llm config
        :param callbacks: A list of BaseCallbackHandlers to add to the chat model.
        :return: A BaseLanguageModel (can be Chat or LLM)
                Can raise a ValueError if the config's class or model_name value is
                unknown to this method.
        """
        # Construct the LLM
        llm: BaseLanguageModel = None
        chat_class: str = config.get("class")
        if chat_class is not None:
            chat_class = chat_class.lower()

        # Take "class" out of config and add "callback".
        config.pop("class")
        config["callbacks"] = callbacks

        # Unpack config in the user-specified class
        if chat_class == "openai":
            llm = ChatOpenAI(**config)
        elif chat_class == "azure-openai":
            llm = AzureChatOpenAI(**config)
        elif chat_class == "anthropic":
            llm = ChatAnthropic(**config)
        elif chat_class == "ollama":
            llm = ChatOllama(**config)
        elif chat_class == "nvidia":
            llm = ChatNVIDIA(**config)
        elif chat_class == "gemini":
            llm = ChatGoogleGenerativeAI(**config)
        else:
            valid_class_map = {
                "openai": "ChatOpenAI",
                "azure-openai": "AzureChatOpenAI",
                "anthropic": "ChatAnthropic",
                "ollama": "ChatOllama",
                "nvidia": "ChatNVIDIA",
                "gemini": "ChatGoogleGenerativeAI",
            }
            available = "\n".join(f"  - '{key}': {val}" for key, val in valid_class_map.items())
            raise ValueError(
                f"Unrecognized model class '{chat_class}'.\n"
                f"Valid class values and their corresponding implementations are:\n{available}"
            )

        return llm
