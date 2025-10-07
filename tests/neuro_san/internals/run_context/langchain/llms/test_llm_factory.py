
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

import json

from langchain_core.language_models.base import BaseLanguageModel
from langchain_openai.chat_models.base import ChatOpenAI

from neuro_san.internals.run_context.langchain.llms.client_policy import ClientPolicy
from neuro_san.internals.run_context.langchain.llms.langchain_llm_factory import LangChainLlmFactory
from neuro_san.internals.run_context.langchain.llms.langchain_llm_resources import LangChainLlmResources
from neuro_san.internals.run_context.langchain.llms.openai_client_policy import OpenAIClientPolicy


class TestLlmFactory(LangChainLlmFactory):
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

    def create_base_chat_model(self, config: Dict[str, Any]) -> BaseLanguageModel:
        """
        Create a LangChainLlmResources instance from the fully-specified llm config.

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

    def create_llm_resources(self, config: Dict[str, Any]) -> LangChainLlmResources:
        """
        Create a LangChainLlmResources instance from the fully-specified llm config.

        :param config: The fully specified llm config which is a product of
                    _create_full_llm_config() above.
        :return: A LangChainLlmResources instance containing
                a BaseLanguageModel (can be Chat or LLM) and a ClientPolicy
                object necessary for managing the model run-time lifecycle.
                Can raise a ValueError if the config's class or model_name value is
                unknown to this method.
        """
        # Construct the LLM
        llm: BaseLanguageModel = None
        client_policy: ClientPolicy = None

        chat_class: str = config.get("class")
        if chat_class is not None:
            chat_class = chat_class.lower()

        model_name: str = config.get("model_name")

        print(f"In TestLlmFactory for {json.dumps(config, sort_keys=True, indent=4)}")
        if chat_class == "test-openai":
            print("Creating test-openai")

            # Create the policy object that allows us to manage the model run-time lifecycle
            client_policy = OpenAIClientPolicy()
            async_client: Any = client_policy.create_client(config)

            # Now construct LLM chat model we will be using:
            llm = ChatOpenAI(
                async_client=async_client,
                model_name=model_name,
                temperature=config.get("temperature"),

                # This next group of params should always be None when we have async_client
                openai_api_key=self.get_value_or_env(config, "openai_api_key",
                                                     "OPENAI_API_KEY", async_client),
                openai_api_base=self.get_value_or_env(config, "openai_api_base",
                                                      "OPENAI_API_BASE", async_client),
                openai_organization=self.get_value_or_env(config, "openai_organization",
                                                          "OPENAI_ORG_ID", async_client),
                openai_proxy=self.get_value_or_env(config, "openai_organization",
                                                   "OPENAI_PROXY", async_client),
                request_timeout=self.get_value_or_env(config, "request_timeout", None, async_client),
                max_retries=self.get_value_or_env(config, "max_retries", None, async_client),

                presence_penalty=config.get("presence_penalty"),
                frequency_penalty=config.get("frequency_penalty"),
                seed=config.get("seed"),
                logprobs=config.get("logprobs"),
                top_logprobs=config.get("top_logprobs"),
                logit_bias=config.get("logit_bias"),
                streaming=True,  # streaming is always on. Without it token counting will not work.
                n=1,  # n is always 1.  neuro-san will only ever consider one chat completion.
                top_p=config.get("top_p"),
                max_tokens=config.get("max_tokens"),  # This is always for output
                tiktoken_model_name=config.get("tiktoken_model_name"),
                stop=config.get("stop"),

                # The following three parameters are for reasoning models only.
                reasoning=config.get("reasoning"),
                reasoning_effort=config.get("reasoning_effort"),
                verbosity=config.get("verbosity"),

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

                # Set stream_usage to True in order to get token counting chunks.
                stream_usage=True
            )

        elif chat_class is None:
            raise ValueError(f"Class name {chat_class} for model_name {model_name} is unspecified.")
        else:
            raise ValueError(f"Class {chat_class} for model_name {model_name} is unrecognized.")

        # Return the LlmResources with the client_policy that was created.
        # That might be None, and that's OK.
        return LangChainLlmResources(llm, client_policy=client_policy)
