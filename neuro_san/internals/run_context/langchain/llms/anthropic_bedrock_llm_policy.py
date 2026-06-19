
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

from langchain_core.language_models.base import BaseLanguageModel

from neuro_san.internals.run_context.langchain.llms.anthropic_llm_policy import AnthropicLlmPolicy
from neuro_san.internals.utils.config_util import ConfigUtil


class AnthropicBedrockLlmPolicy(AnthropicLlmPolicy):
    """
    Implementation of the LlmPolicy for Anthropic Claude models hosted on AWS Bedrock,
    via langchain-aws's ChatAnthropicBedrock.

    ChatAnthropicBedrock is a subclass of ChatAnthropic that authenticates with AWS
    credentials and routes requests through Anthropic's AnthropicBedrock SDK client
    (not boto3 — the existing "bedrock" class handles the boto3-based ChatBedrock).
    Use this class when you want Anthropic-on-Bedrock with the same parameter surface
    as the direct Anthropic API (thinking, effort, mcp_servers, context_management,
    etc.).

    The async web client is built lazily by the underlying ChatAnthropic via a
    cached_property, so the type-2 cleanup pattern inherited from AnthropicLlmPolicy
    (reach into self.llm._async_client and aclose it) applies here unchanged.
    """

    def create_llm(self, config: Dict[str, Any], model_name: str, client: Any) -> BaseLanguageModel:
        """
        Create a ChatAnthropicBedrock BaseLanguageModel.

        :param config: The fully specified llm config
        :param model_name: The Bedrock inference-profile id, e.g.
                "us.anthropic.claude-sonnet-4-6" or
                "anthropic.claude-sonnet-4-5-20250929-v1:0".
        :param client: Ignored — ChatAnthropicBedrock builds its own client.
        :return: A BaseLanguageModel
        """
        _ = client

        # Use lazy loading to prevent installing the world. The `[anthropic]` extra
        # pulls in the `anthropic` SDK which ChatAnthropicBedrock needs at runtime.
        # pylint: disable=invalid-name
        ChatAnthropicBedrock = self.resolver.resolve_class_in_module(
            "ChatAnthropicBedrock",
            module_name="langchain_aws.chat_models.anthropic",
            install_if_missing="langchain-aws[anthropic]")

        llm = ChatAnthropicBedrock(
            model_name=model_name,
            max_tokens=config.get("max_tokens"),  # This is always for output
            temperature=config.get("temperature"),
            top_k=config.get("top_k"),
            top_p=config.get("top_p"),
            default_request_timeout=config.get("default_request_timeout"),
            max_retries=config.get("max_retries"),
            stop_sequences=config.get("stop_sequences"),
            default_headers=config.get("default_headers"),
            betas=config.get("betas"),

            # AWS authentication. Each falls back to its standard AWS env var if
            # unset in the llm_config, matching ChatAnthropicBedrock's own defaults.
            region_name=self.get_value_or_env(config, "region_name", "AWS_REGION"),
            aws_access_key_id=self.get_value_or_env(config, "aws_access_key_id",
                                                    "AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=self.get_value_or_env(config, "aws_secret_access_key",
                                                        "AWS_SECRET_ACCESS_KEY"),
            aws_session_token=self.get_value_or_env(config, "aws_session_token",
                                                    "AWS_SESSION_TOKEN"),

            # Streaming is configurable via the "streaming" key in llm_config; defaults
            # to False so existing agents keep their long-standing non-streaming behavior.
            # We pass streaming explicitly (rather than relying on LangChain's default) so
            # that langchain_core._should_stream() picks up the configured value even when
            # a streaming-aware callback is attached. Token usage is collected from
            # AIMessage.usage_metadata in LlmTokenCallbackHandler regardless of streaming
            # mode; stream_usage tracks streaming so usage frames flow only when streaming.
            streaming=ConfigUtil.get_bool(config, "streaming"),
            stream_usage=ConfigUtil.get_bool(config, "streaming"),
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
