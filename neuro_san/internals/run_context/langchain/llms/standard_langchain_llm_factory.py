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

from leaf_common.config.resolver import Resolver

from neuro_san.internals.run_context.langchain.llms.anthropic_llm_policy import AnthropicLlmPolicy
from neuro_san.internals.run_context.langchain.llms.azure_llm_policy import AzureLlmPolicy
from neuro_san.internals.run_context.langchain.llms.bedrock_llm_policy import BedrockLlmPolicy
from neuro_san.internals.run_context.langchain.llms.llm_policy import LlmPolicy
from neuro_san.internals.run_context.langchain.llms.langchain_llm_factory import LangChainLlmFactory
from neuro_san.internals.run_context.langchain.llms.langchain_llm_resources import LangChainLlmResources
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

        "prompt_token_fraction"     The fraction of total tokens (not necessarily words
                                    or letters) to use for a prompt. Each model_name
                                    has a documented number of max_tokens it can handle
                                    which is a total count of message + response tokens
                                    which goes into the calculation involved in
                                    get_max_prompt_tokens().
                                    By default, the value is 0.5.

        "max_tokens"                The maximum number of tokens to use in
                                    get_max_prompt_tokens(). By default, this comes from
                                    the model description in this class.
    """

    def __init__(self):
        """
        Constructor
        """
        self.policy_name_to_class: Dict[str, LlmPolicy] = {
            "openai": OpenAILlmPolicy,
            "azure-openai": AzureLlmPolicy,
            "bedrock": BedrockLlmPolicy,
            "anthropic": AnthropicLlmPolicy
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

        # Set up a resolver to use to resolve lazy imports of classes from
        # langchain_* packages to prevent installing the world.
        resolver = Resolver()

        # Get from table of policy classes
        llm_policy: LlmPolicy = None
        policy_class: Type[LlmPolicy] = self.policy_name_to_class.get(chat_class)
        if policy_class is not None:
            llm_policy = policy_class()
            llm, llm_policy = llm_policy.create_llm_resources_components(config)

        elif chat_class == "ollama":

            # Use lazy loading to prevent installing the world
            # pylint: disable=invalid-name
            ChatOllama = resolver.resolve_class_in_module("ChatOllama",
                                                          module_name="langchain_ollama",
                                                          install_if_missing="langchain-ollama")
            # Higher temperature is more random
            llm = ChatOllama(
                model=model_name,
                mirostat=config.get("mirostat"),
                mirostat_eta=config.get("mirostat_eta"),
                mirostat_tau=config.get("mirostat_tau"),
                num_ctx=config.get("num_ctx"),
                num_gpu=config.get("num_gpu"),
                num_thread=config.get("num_thread"),
                num_predict=config.get("num_predict", config.get("max_tokens")),
                reasoning=config.get("reasoning"),
                repeat_last_n=config.get("repeat_last_n"),
                repeat_penalty=config.get("repeat_penalty"),
                temperature=config.get("temperature"),
                seed=config.get("seed"),
                stop=config.get("stop"),
                tfs_z=config.get("tfs_z"),
                top_k=config.get("top_k"),
                top_p=config.get("top_p"),
                keep_alive=config.get("keep_alive"),
                base_url=config.get("base_url"),

                # If omitted, this defaults to the global verbose value,
                # accessible via langchain_core.globals.get_verbose():
                # https://github.com/langchain-ai/langchain/blob/master/libs/core/langchain_core/globals.py#L53
                #
                # However, accessing the global verbose value during concurrent initialization
                # can trigger the following warning:
                #
                # UserWarning: Importing verbose from langchain root module is no longer supported.
                # Please use langchain.globals.set_verbose() / langchain.globals.get_verbose() instead.
                # old_verbose = langchain.verbose
                #
                # To prevent this, we explicitly set verbose=False here (which matches the default
                # global verbose value) so that the warning is never triggered.
                verbose=False,
            )
        elif chat_class == "nvidia":

            # Use lazy loading to prevent installing the world
            # pylint: disable=invalid-name
            ChatNVIDIA = resolver.resolve_class_in_module("ChatNVIDIA",
                                                          module_name="langchain_nvidia_ai_endpoints",
                                                          install_if_missing="langchain-nvidia-ai-endpoints")
            # Higher temperature is more random
            llm = ChatNVIDIA(
                base_url=config.get("base_url"),
                model=model_name,
                temperature=config.get("temperature"),
                max_tokens=config.get("max_tokens"),
                top_p=config.get("top_p"),
                seed=config.get("seed"),
                stop=config.get("stop"),

                # If omitted, this defaults to the global verbose value,
                # accessible via langchain_core.globals.get_verbose():
                # https://github.com/langchain-ai/langchain/blob/master/libs/core/langchain_core/globals.py#L53
                #
                # However, accessing the global verbose value during concurrent initialization
                # can trigger the following warning:
                #
                # UserWarning: Importing verbose from langchain root module is no longer supported.
                # Please use langchain.globals.set_verbose() / langchain.globals.get_verbose() instead.
                # old_verbose = langchain.verbose
                #
                # To prevent this, we explicitly set verbose=False here (which matches the default
                # global verbose value) so that the warning is never triggered.
                verbose=False,
                nvidia_api_key=self.get_value_or_env(config, "nvidia_api_key",
                                                     "NVIDIA_API_KEY"),
                nvidia_base_url=self.get_value_or_env(config, "nvidia_base_url",
                                                      "NVIDIA_BASE_URL"),
            )
        elif chat_class == "gemini":

            # Use lazy loading to prevent installing the world
            # pylint: disable=invalid-name
            ChatGoogleGenerativeAI = resolver.resolve_class_in_module("ChatGoogleGenerativeAI",
                                                                      module_name="langchain_google_genai.chat_models",
                                                                      install_if_missing="langchain-google-genai")
            llm = ChatGoogleGenerativeAI(
                model=model_name,
                google_api_key=self.get_value_or_env(config, "google_api_key",
                                                     "GOOGLE_API_KEY"),
                max_retries=config.get("max_retries"),
                max_tokens=config.get("max_tokens"),  # This is always for output
                n=config.get("n"),
                temperature=config.get("temperature"),
                timeout=config.get("timeout"),
                top_k=config.get("top_k"),
                top_p=config.get("top_p"),

                # If omitted, this defaults to the global verbose value,
                # accessible via langchain_core.globals.get_verbose():
                # https://github.com/langchain-ai/langchain/blob/master/libs/core/langchain_core/globals.py#L53
                #
                # However, accessing the global verbose value during concurrent initialization
                # can trigger the following warning:
                #
                # UserWarning: Importing verbose from langchain root module is no longer supported.
                # Please use langchain.globals.set_verbose() / langchain.globals.get_verbose() instead.
                # old_verbose = langchain.verbose
                #
                # To prevent this, we explicitly set verbose=False here (which matches the default
                # global verbose value) so that the warning is never triggered.
                verbose=False,
            )
        elif chat_class is None:
            raise ValueError(f"Class name {chat_class} for model_name {model_name} is unspecified.")
        else:
            raise ValueError(f"Class {chat_class} for model_name {model_name} is unrecognized.")

        # Return the LlmResources with the llm_policy that was created.
        # That might be None, and that's OK.
        return LangChainLlmResources(llm, llm_policy=llm_policy)
