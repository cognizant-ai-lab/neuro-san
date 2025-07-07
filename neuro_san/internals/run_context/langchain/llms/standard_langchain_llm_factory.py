
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
from langchain_aws import ChatBedrock
from langchain_core.callbacks.base import BaseCallbackHandler
from langchain_core.language_models.base import BaseLanguageModel
from langchain_google_genai.chat_models import ChatGoogleGenerativeAI
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from langchain_ollama import ChatOllama
from langchain_openai.chat_models.azure import AzureChatOpenAI
from langchain_openai.chat_models.base import ChatOpenAI

from neuro_san.internals.run_context.langchain.llms.langchain_llm_factory import LangChainLlmFactory


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
                                    By default the value is 0.5.

        "max_tokens"                The maximum number of tokens to use in
                                    get_max_prompt_tokens(). By default this comes from
                                    the model description in this class.
    """

    def create_base_chat_model(self, config: Dict[str, Any],
                               callbacks: List[BaseCallbackHandler] = None) -> BaseLanguageModel:
        """
        Create a BaseLanguageModel from the fully-specified llm config.
        :param config: The fully specified llm config which is a product of
                    _create_full_llm_config() above.
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

        model_name: str = config.get("model_name")

        if chat_class == "openai":
            llm = ChatOpenAI(
                            model_name=model_name,
                            temperature=config.get("temperature"),
                            openai_api_key=self.get_value_or_env(config, "openai_api_key",
                                                                 "OPENAI_API_KEY"),
                            openai_api_base=self.get_value_or_env(config, "openai_api_base",
                                                                  "OPENAI_API_BASE"),
                            openai_organization=self.get_value_or_env(config, "openai_organization",
                                                                      "OPENAI_ORG_ID"),
                            openai_proxy=self.get_value_or_env(config, "openai_organization",
                                                               "OPENAI_PROXY"),
                            request_timeout=config.get("request_timeout"),
                            max_retries=config.get("max_retries"),
                            presence_penalty=config.get("presence_penalty"),
                            frequency_penalty=config.get("frequency_penalty"),
                            seed=config.get("seed"),
                            logprobs=config.get("logprobs"),
                            top_logprobs=config.get("top_logprobs"),
                            logit_bias=config.get("logit_bias"),
                            streaming=True,     # streaming is always on. Without it token counting will not work.
                            n=1,                # n is always 1.  neuro-san will only ever consider one chat completion.
                            top_p=config.get("top_p"),
                            max_tokens=config.get("max_tokens"),    # This is always for output
                            tiktoken_model_name=config.get("tiktoken_model_name"),
                            stop=config.get("stop"),

                            # Set stream_usage to True in order to get token counting chunks.
                            stream_usage=True,
                            callbacks=callbacks)
        elif chat_class == "azure-openai":
            model_kwargs: Dict[str, Any] = {
                "stream_options": {
                    "include_usage": True
                }
            }
            openai_api_key: str = self.get_value_or_env(config, "openai_api_key", "AZURE_OPENAI_API_KEY")
            if openai_api_key is None:
                openai_api_key = self.get_value_or_env(config, "openai_api_key", "OPENAI_API_KEY")
            llm = AzureChatOpenAI(
                            model_name=model_name,
                            temperature=config.get("temperature"),
                            openai_api_key=openai_api_key,
                            openai_api_base=self.get_value_or_env(config, "openai_api_base",
                                                                  "OPENAI_API_BASE"),
                            openai_organization=self.get_value_or_env(config, "openai_organization",
                                                                      "OPENAI_ORG_ID"),
                            openai_proxy=self.get_value_or_env(config, "openai_organization",
                                                               "OPENAI_PROXY"),
                            request_timeout=config.get("request_timeout"),
                            max_retries=config.get("max_retries"),
                            presence_penalty=config.get("presence_penalty"),
                            frequency_penalty=config.get("frequency_penalty"),
                            seed=config.get("seed"),
                            logprobs=config.get("logprobs"),
                            top_logprobs=config.get("top_logprobs"),
                            logit_bias=config.get("logit_bias"),
                            streaming=True,     # streaming is always on. Without it token counting will not work.
                            n=1,                # n is always 1.  neuro-san will only ever consider one chat completion.
                            top_p=config.get("top_p"),
                            max_tokens=config.get("max_tokens"),    # This is always for output
                            tiktoken_model_name=config.get("tiktoken_model_name"),
                            stop=config.get("stop"),

                            # Azure-specific
                            azure_endpoint=self.get_value_or_env(config, "azure_endpoint",
                                                                 "AZURE_OPENAI_ENDPOINT"),
                            deployment_name=config.get("deployment_name"),
                            openai_api_version=self.get_value_or_env(config, "openai_api_version",
                                                                     "OPENAI_API_VERSION"),

                            # AD here means "ActiveDirectory"
                            azure_ad_token=self.get_value_or_env(config, "azure_ad_token",
                                                                 "AZURE_OPENAI_AD_TOKEN"),
                            model_version=config.get("model_version"),
                            openai_api_type=self.get_value_or_env(config, "openai_api_type",
                                                                  "OPENAI_API_TYPE"),
                            # Needed for token counting
                            model_kwargs=model_kwargs,
                            callbacks=callbacks)
        elif chat_class == "anthropic":
            llm = ChatAnthropic(
                            model_name=model_name,
                            max_tokens=config.get("max_tokens"),    # This is always for output
                            temperature=config.get("temperature"),
                            top_k=config.get("top_k"),
                            top_p=config.get("top_p"),
                            default_request_timeout=config.get("default_request_timeout"),
                            max_retries=config.get("max_retries"),
                            stop_sequences=config.get("stop_sequences"),
                            anthropic_api_url=self.get_value_or_env(config, "anthropic_api_url",
                                                                    "ANTHROPIC_API_URL"),
                            anthropic_api_key=self.get_value_or_env(config, "anthropic_api_key",
                                                                    "ANTHROPIC_API_KEY"),
                            streaming=True,     # streaming is always on. Without it token counting will not work.
                            # Set stream_usage to True in order to get token counting chunks.
                            stream_usage=True,
                            callbacks=callbacks)
        elif chat_class == "ollama":
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

                            callbacks=callbacks)
        elif chat_class == "nvidia":
            # Higher temperature is more random
            llm = ChatNVIDIA(
                            base_url=config.get("base_url"),
                            model=model_name,
                            temperature=config.get("temperature"),
                            max_tokens=config.get("max_tokens"),
                            top_p=config.get("top_p"),
                            seed=config.get("seed"),
                            stop=config.get("stop"),
                            nvidia_api_key=self.get_value_or_env(config, "nvidia_api_key",
                                                                 "NVIDIA_API_KEY"),
                            nvidia_base_url=self.get_value_or_env(config, "nvidia_base_url",
                                                                  "NVIDIA_BASE_URL"),
                            callbacks=callbacks)
        elif chat_class == "gemini":
            llm = ChatGoogleGenerativeAI(
                            model=model_name,
                            google_api_key=self.get_value_or_env(config, "google_api_key",
                                                                 "GOOGLE_API_KEY"),
                            max_retries=config.get("max_retries"),
                            max_tokens=config.get("max_tokens"),    # This is always for output
                            n=config.get("n"),
                            temperature=config.get("temperature"),
                            timeout=config.get("timeout"),
                            top_k=config.get("top_k"),
                            top_p=config.get("top_p"),
                            callbacks=callbacks)
        elif chat_class == "bedrock":
            llm = ChatBedrock(
                aws_access_key_id=self.get_value_or_env(config, "aws_access_key_id", "AWS_ACCESS_KEY_ID"),
                aws_secret_access_key=self.get_value_or_env(config, "aws_secret_access_key", "AWS_SECRET_ACCESS_KEY"),
                aws_session_token=self.get_value_or_env(config, "aws_session_token", "AWS_SESSION_TOKEN"),
                base_model_id=config.get("base_model_id"),
                beta_use_converse_api=config.get("beta_use_converse_api"),
                cache=config.get("cache"),
                config=config.get("config"),
                credentials_profile_name=config.get("credentials_profile_name"),
                custom_get_token_ids=config.get("custom_get_token_ids"),
                endpoint_url=config.get("endpoint_url"),
                guardrails=config.get("guardrails"),
                max_tokens=config.get("max_tokens"),
                metadata=config.get("metadata"),
                provider=config.get("provider"),
                rate_limiter=config.get("rate_limiter"),
                region_name=config.get("region_name"),
                stop_sequences=config.get("stop_sequences"),
                streaming=True,
                system_prompt_with_tools=config.get("system_prompt_with_tools"),
                tags=config.get("tags"),
                temperature=config.get("temperature"),
                callbacks=callbacks)
        elif chat_class is None:
            raise ValueError(f"Class name {chat_class} for model_name {model_name} is unspecified.")
        else:
            raise ValueError(f"Class {chat_class} for model_name {model_name} is unrecognized.")

        return llm
