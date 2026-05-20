
# Copyright © 2023-2026 Cognizant Technology Solutions Corp, www.cognizant.com.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
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
            # Disable streaming: neuro-san does not consume per-token chunks from the model,
            # and disabling streaming reduces per-request LangChain pipeline overhead.
            # Token usage is collected from AIMessage.usage_metadata in LlmTokenCallbackHandler.
            # We set streaming explicitly (rather than relying on the False default) so that
            # langchain_core._should_stream() recognizes it as opted-out
            # even when a streaming-aware callback is attached.
            streaming=False,
            stream_usage=False,  # Don't even include token usage in the streaming response, since we're not streaming
            thinking=config.get("thinking"),
            effort=config.get("effort"),
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
