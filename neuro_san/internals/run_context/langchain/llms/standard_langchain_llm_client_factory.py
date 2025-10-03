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

from httpx import AsyncClient

from leaf_common.config.resolver import Resolver

from neuro_san.internals.run_context.langchain.llms.httpx_langchain_llm_client import HttpxLangChainLlmClient
from neuro_san.internals.run_context.langchain.llms.langchain_llm_client import LangChainLlmClient
from neuro_san.internals.run_context.langchain.llms.langchain_llm_client_factory import LangChainLlmClientFactory


class StandardLangChainLlmClientFactory(LangChainLlmClientFactory):
    """
    Factory class for creating LangChainLlmClient instances for Chat and LLM operations
    """

    def create_llm_client(self, config: Dict[str, Any]) -> LangChainLlmClient:
        """
        Create an LangChainLlmClient instance from the fully-specified llm config.
        :param config: The fully specified llm config
        :return: A LangChainLlmClient instance.
                Can be None if the llm class in the config does not need a client.
                Can raise a ValueError if the config's class or model_name value is
                unknown to this method.
        """
        # pylint: disable=too-many-locals
        # Construct the LLM
        llm_client: LangChainLlmClient = None
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

        if chat_class == "openai":

            # OpenAI is the one chat class that we do not require any extra installs.
            # This is what we want to work out of the box.
            # Nevertheless, have it go through the same lazy-loading resolver rigamarole as the others.

            # pylint: disable=invalid-name
            AsyncOpenAI = resolver.resolve_class_in_module("AsyncOpenAI",
                                                           module_name="openai",
                                                           install_if_missing="langchain-openai")

            # Our run-time model resource here is httpx client which we need to control directly:
            openai_proxy = self.get_value_or_env(config, "openai_proxy", "OPENAI_PROXY")
            request_timeout = config.get("request_timeout")
            http_client = AsyncClient(proxy=openai_proxy, timeout=request_timeout)

            async_openai_client = AsyncOpenAI(
                api_key=self.get_value_or_env(config, "openai_api_key", "OPENAI_API_KEY"),
                base_url=self.get_value_or_env(config, "openai_api_base", "OPENAI_API_BASE"),
                organization=self.get_value_or_env(config, "openai_organization", "OPENAI_ORG_ID"),
                timeout=request_timeout,
                max_retries=config.get("max_retries"),
                http_client=http_client
            )

            llm_client = HttpxLangChainLlmClient(http_client, async_openai_client)

        elif chat_class == "azure-openai":

            # pylint: disable=invalid-name
            AsyncAzureOpenAI = resolver.resolve_class_in_module("AsyncAzureOpenAI",
                                                                module_name="openai",
                                                                install_if_missing="langchain-openai")

            # Our run-time model resource here is httpx client which we need to control directly:
            openai_proxy = self.get_value_or_env(config, "openai_proxy", "OPENAI_PROXY")
            request_timeout = config.get("request_timeout")
            http_client = AsyncClient(proxy=openai_proxy, timeout=request_timeout)

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

            async_azure_client = AsyncAzureOpenAI(
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
                timeout=request_timeout,
                max_retries=config.get("max_retries"),
                default_headers=default_headers,
                # default_query     - don't understand enough to set, but set in langchain_openai
                http_client=http_client
            )

            llm_client = HttpxLangChainLlmClient(http_client, async_azure_client)

        elif chat_class == "anthropic":

            # Not yet
            # Anthropic models only support _async_client() as a cached_property, not as a passed-in arg.
            # In LlmFactory, we grab hold of the client after we create the BaseLanguageModel.
            # That's all we can do.
            llm_client = None

        elif chat_class == "ollama":

            # Never. Ollama models are local
            llm_client = None

        elif chat_class == "nvidia":

            # Not yet
            llm_client = None

        elif chat_class == "gemini":

            # Not yet
            llm_client = None

        elif chat_class == "bedrock":

            # Note: ChatBedrock only ever uses a synchronous boto3 client to access
            #       any llm and there are no aioboto3 hooks yet. Not the greatest choice
            #       for a performant asynchronous server.
            # In LlmFactory, we grab hold of the client after we create the BaseLanguageModel.
            # That's all we can do.

            llm_client = None

        elif chat_class is None:
            raise ValueError(f"Class name {chat_class} for model_name {model_name} is unspecified.")
        else:
            raise ValueError(f"Class {chat_class} for model_name {model_name} is unrecognized.")

        return llm_client
