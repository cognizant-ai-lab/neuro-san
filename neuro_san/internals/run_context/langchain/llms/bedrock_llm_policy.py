
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

from langchain_core.language_models.base import BaseLanguageModel

from neuro_san.internals.run_context.langchain.llms.llm_policy import LlmPolicy


class BedrockLlmPolicy(LlmPolicy):
    """
    LlmPolicy implementation for Bedrock.

    Bedrock does not allow for passing in async web clients.
    As a matter of fact, all of its clients are synchronous,
    which is not the best for an async service.
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
        ChatBedrock = self.resolver.resolve_class_in_module("ChatBedrock",
                                                            module_name="langchain_aws",
                                                            install_if_missing="langchain-aws")
        llm = ChatBedrock(
            model=model_name,
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
        if self.llm.client is not None:
            # This is a boto3 client
            self.llm.client.close()

        if self.llm.bedrock_client is not None:
            # This is a boto3 client
            self.llm.bedrock_client.close()

        # Let's not do this again, shall we?
        self.llm = None
