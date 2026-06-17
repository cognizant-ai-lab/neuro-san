
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
from neuro_san.internals.utils.config_util import ConfigUtil


class OpenRouterLlmPolicy(LlmPolicy):
    """
    Implementation of the LlmPolicy for OpenRouter chat models.

    OpenRouter is a unified API that fronts hundreds of models from many
    providers (OpenAI, Anthropic, Google, Meta, etc.). Models are addressed
    as "provider/model", e.g. "anthropic/claude-sonnet-4-5".

    ChatOpenRouter builds its own openrouter SDK client internally and does
    not allow for passing in an externally managed async web client.
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
        ChatOpenRouter = self.resolver.resolve_class_in_module("ChatOpenRouter",
                                                               module_name="langchain_openrouter.chat_models",
                                                               install_if_missing="langchain-openrouter")

        llm = ChatOpenRouter(
            model=model_name,
            api_key=self.get_value_or_env(config, "openrouter_api_key",
                                          "OPENROUTER_API_KEY"),
            base_url=self.get_value_or_env(config, "openrouter_api_base",
                                           "OPENROUTER_API_BASE"),
            timeout=config.get("request_timeout"),
            max_retries=config.get("max_retries"),
            temperature=config.get("temperature"),
            max_tokens=config.get("max_tokens"),
            top_p=config.get("top_p"),
            frequency_penalty=config.get("frequency_penalty"),
            presence_penalty=config.get("presence_penalty"),
            seed=config.get("seed"),
            stop_sequences=config.get("stop"),
            # Streaming is configurable via the "streaming" key in llm_config; defaults
            # to False so existing agents keep their long-standing non-streaming behavior.
            # We pass streaming explicitly (rather than relying on LangChain's default) so
            # that langchain_core._should_stream() picks up the configured value even when
            # a streaming-aware callback is attached. Token usage is collected from
            # AIMessage.usage_metadata in LlmTokenCallbackHandler regardless of streaming
            # mode; stream_usage tracks streaming so usage frames flow only when streaming.
            streaming=ConfigUtil.get_bool(config, "streaming"),
            stream_usage=ConfigUtil.get_bool(config, "streaming"),
            reasoning=config.get("reasoning"),
            openrouter_provider=config.get("openrouter_provider"),
            route=config.get("route"),
            session_id=config.get("session_id"),
            trace=config.get("trace"),
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

        # Do the necessary reach-ins to successfully shut down the web client.
        # ChatOpenRouter wraps an openrouter.OpenRouter SDK client which itself
        # owns the httpx clients. Best-effort close, since the SDK's close API
        # is not part of LangChain's public contract.
        sdk_client: Any = getattr(self.llm, "client", None)
        if sdk_client is not None:
            for attr in ("aclose", "close"):
                method = getattr(sdk_client, attr, None)
                if method is None:
                    continue
                with suppress(Exception):
                    result = method()
                    if hasattr(result, "__await__"):
                        await result
                break

        self.llm = None
