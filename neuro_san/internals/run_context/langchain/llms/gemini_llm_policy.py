
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


class GeminiLlmPolicy(LlmPolicy):
    """
    LlmPolicy implementation for Gemini.
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
        ChatGoogleGenerativeAI = self.resolver.resolve_class_in_module("ChatGoogleGenerativeAI",
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
            thinking_level=config.get("thinking_level"),
            thinking_budget=config.get("thinking_budget"),

            # Disable streaming: neuro-san does not consume per-token chunks from the model,
            # and disabling streaming reduces per-request LangChain pipeline overhead.
            # We pass streaming explicitly (rather than relying on the False default) so that
            # langchain_core._should_stream() recognizes it as opted-out even when a
            # streaming-aware callback handler is attached to the run manager.
            streaming=False,

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
        # This used to be a v1betaGenerativeServiceAsyncClient, aka
        # google.ai.generativelanguage_v1beta.GenerativeServiceAsyncClient.
        # however, langchain-google-genai==4.0.0 migrated to google-genai,
        # and now When ChatGoogleGenerativeAI is instantiated, it creates google.genai.Client
        # via the validate_environment method
        # (https://github.com/langchain-ai/langchain-google/blob/main/libs/genai/langchain_google_genai/
        # chat_models.py#L2306).
        #
        # The google.genai.Client internally creates both sync and async client instances,
        # so both Client and AsyncClient (accessible via client.aio) are instantiated
        # at this time.
        #
        # The async_client @property
        # (https://github.com/langchain-ai/langchain-google/blob/main/libs/genai/langchain_google_genai/
        # chat_models.py#L2476)
        # simply returns self.client.aio - it doesn't create a new client, just provides
        # convenient access to the already-instantiated AsyncClient.
        #
        # Therefore, both clients exist immediately upon ChatGoogleGenerativeAI instantiation
        # and both should be closed during cleanup.
        #
        # References:
        # https://github.com/langchain-ai/langchain-google/releases/tag/libs%2Fgenai%2Fv4.0.0
        # https://github.com/googleapis/python-genai/blob/main/google/genai/client.py
        # https://reference.langchain.com/python/integrations/langchain_google_genai/ChatGoogleGenerativeAI/
        # #langchain_google_genai.ChatGoogleGenerativeAI.async_client

        # Close sync client
        if self.llm.client is not None:
            with suppress(Exception):
                self.llm.client.close()

        # Close async client
        if self.llm.async_client is not None:
            with suppress(Exception):
                await self.llm.async_client.aclose()

        # Let's not do this again, shall we?
        self.llm = None
