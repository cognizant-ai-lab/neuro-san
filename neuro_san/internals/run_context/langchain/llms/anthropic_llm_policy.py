
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

from contextlib import suppress

from langchain_core.language_models.base import BaseLanguageModel

from neuro_san.internals.run_context.langchain.llms.llm_policy import LlmPolicy


class AnthropicLlmPolicy(LlmPolicy):
    """
    Implementation of the LlmPolicy for Anthtropic chat models.

    Anthropic chat models do not allow for passing in an externally managed
    async web client.
    """

    def create_llm(self, config: Dict[str, Any], model_name: str, client: Any) -> BaseLanguageModel:
        """
        Create a BaseLanguageModel instance from the fully-specified llm config
        for the llm class that the implementation supports.  Chat models are usually
        per-provider, where the specific model itself is an argument to its constructor.

        :param config: The fully specified llm config
        :param model_name: The name of the model
        :param client: The web client to use (if any)
        :return: A BaseLanguageModel (can be Chat or LLM)
        """
        # Use lazy loading to prevent installing the world
        # pylint: disable=invalid-name
        ChatAnthropic = self.resolver.resolve_class_in_module("ChatAnthropic",
                                                              module_name="langchain_anthropic.chat_models",
                                                              install_if_missing="langchain-anthropic")

        llm = ChatAnthropic(
            model_name=model_name,
            max_tokens=config.get("max_tokens"),  # This is always for output
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
            default_headers=config.get("default_headers"),
            betas=config.get("betas"),
            streaming=True,  # streaming is always on. Without it token counting will not work.
            # Set stream_usage to True in order to get token counting chunks.
            stream_usage=True,
            thinking=config.get("thinking"),
            mcp_servers=config.get("mcp_servers"),
            context_management=config.get("context_management"),
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
        return llm

    async def delete_resources(self):
        """
        Release the run-time resources used by the model
        """
        if self.llm is None:
            return

        # Do the necessary reach-ins to successfully shut down the web client

        # This is really an anthropic.AsyncClient, but we don't really want to do the Resolver here.
        # Note we don't want to do this in the constructor, as AnthropicChat lazily
        # creates these as needed via a cached_property that needs to be done in its own time
        # via Anthropic infrastructure.  By the time we get here, it's already been created.
        anthropic_async_client: Any = self.llm._async_client     # pylint:disable=protected-access

        if anthropic_async_client is not None:
            with suppress(Exception):
                await anthropic_async_client.aclose()

        # Let's not do this again, shall we?
        self.llm = None
