
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

from neuro_san.internals.run_context.langchain.llms.openai_llm_policy import OpenAILlmPolicy


class AzureLlmPolicy(OpenAILlmPolicy):
    """
    LlmPolicy implementation for OpenAI via Azure.

    OpenAI's BaseLanguageModel implementations do allow us to pass in a web client
    as an argument, so this implementation takes advantage of the create_client()
    method to do that. Worth noting that where many other implementations might care about
    the llm reference, because of our create_client() implementation, we do not.
    """

    def create_client(self, config: Dict[str, Any]) -> Any:
        """
        Creates the web client to used by a BaseLanguageModel to be
        constructed in the future.  Neuro SAN infrastructures prefers that this
        be an asynchronous client, however we realize some BaseLanguageModels
        do not support that (even though they should!).

        Implementations should retain any references to state that needs to be cleaned up
        in the delete_resources() method.

        :param config: The fully specified llm config
        :return: The web client that accesses the LLM.
                By default this is None, as many BaseLanguageModels
                do not allow a web client to be passed in as an arg.
        """
        # OpenAI is the one chat class that we do not require any extra installs.
        # This is what we want to work out of the box.
        # Nevertheless, have it go through the same lazy-loading resolver rigamarole as the others.

        # pylint: disable=invalid-name
        AsyncAzureOpenAI = self.resolver.resolve_class_in_module("AsyncAzureOpenAI",
                                                                 module_name="openai",
                                                                 install_if_missing="langchain-openai")

        self.create_http_client(config)

        # Prepare some more complex args
        openai_api_key: str = self.get_value_or_env(config, "openai_api_key", "AZURE_OPENAI_API_KEY")
        if openai_api_key is None:
            openai_api_key = self.get_value_or_env(config, "openai_api_key", "OPENAI_API_KEY")

        # From lanchain_openai.chat_models.azure.py
        default_headers: Dict[str, str] = {}
        default_headers = config.get("default_headers", default_headers)
        default_headers.update({
            "User-Agent": "langchain-partner-python-azure-openai",
        })

        self.async_openai_client = AsyncAzureOpenAI(
            azure_endpoint=self.get_value_or_env(config, "azure_endpoint",
                                                 "AZURE_OPENAI_ENDPOINT"),
            deployment_name=self.get_value_or_env(config, "deployment_name",
                                                  "AZURE_OPENAI_DEPLOYMENT_NAME"),
            api_version=self.get_value_or_env(config, "openai_api_version",
                                              "OPENAI_API_VERSION"),
            api_key=openai_api_key,
            # AD here means "ActiveDirectory"
            azure_ad_token=self.get_value_or_env(config, "azure_ad_token",
                                                 "AZURE_OPENAI_AD_TOKEN"),
            # azure_ad_token_provider is a complex object, and we can't set that through config

            organization=self.get_value_or_env(config, "openai_organization", "OPENAI_ORG_ID"),
            # project           - not set in langchain_openai
            # webhook_secret    - not set in langchain_openai
            base_url=self.get_value_or_env(config, "openai_api_base", "OPENAI_API_BASE"),
            timeout=config.get("request_timeout"),
            max_retries=config.get("max_retries"),
            default_headers=default_headers,
            # default_query     - don't understand enough to set, but set in langchain_openai
            http_client=self.http_client
        )

        # We retain the async_openai_client reference, but we hand back this reach-in
        # to pass to the BaseLanguageModel constructor.
        return self.async_openai_client.chat.completions

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
        model_kwargs: Dict[str, Any] = {
            "stream_options": {
                "include_usage": True
            }
        }

        # AzureChatOpenAI just happens to come with langchain_openai
        # pylint: disable=invalid-name
        AzureChatOpenAI = self.resolver.resolve_class_in_module("AzureChatOpenAI",
                                                                module_name="langchain_openai.chat_models.azure",
                                                                install_if_missing="langchain-openai")
        # Prepare some more complex args
        openai_api_key: str = self.get_value_or_env(config, "openai_api_key", "AZURE_OPENAI_API_KEY", client)
        if openai_api_key is None:
            openai_api_key = self.get_value_or_env(config, "openai_api_key", "OPENAI_API_KEY", client)

        llm = AzureChatOpenAI(
            async_client=client,
            model_name=model_name,
            temperature=config.get("temperature"),

            # This next group of params should always be None when we have client
            openai_api_key=openai_api_key,
            openai_api_base=self.get_value_or_env(config, "openai_api_base",
                                                  "OPENAI_API_BASE", client),
            openai_organization=self.get_value_or_env(config, "openai_organization",
                                                      "OPENAI_ORG_ID", client),
            openai_proxy=self.get_value_or_env(config, "openai_proxy",
                                               "OPENAI_PROXY", client),
            request_timeout=self.get_value_or_env(config, "request_timeout", None, client),
            max_retries=self.get_value_or_env(config, "max_retries", None, client),

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

            # Azure-specific group that should be None if we have an client
            azure_endpoint=self.get_value_or_env(config, "azure_endpoint",
                                                 "AZURE_OPENAI_ENDPOINT", client),
            deployment_name=self.get_value_or_env(config, "deployment_name",
                                                  "AZURE_OPENAI_DEPLOYMENT_NAME", client),
            openai_api_version=self.get_value_or_env(config, "openai_api_version",
                                                     "OPENAI_API_VERSION", client),
            # AD here means "ActiveDirectory"
            azure_ad_token=self.get_value_or_env(config, "azure_ad_token",
                                                 "AZURE_OPENAI_AD_TOKEN", client),
            openai_api_type=self.get_value_or_env(config, "openai_api_type",
                                                  "OPENAI_API_TYPE", client),

            model_version=config.get("model_version"),

            # Needed for token counting
            model_kwargs=model_kwargs,
        )

        return llm
