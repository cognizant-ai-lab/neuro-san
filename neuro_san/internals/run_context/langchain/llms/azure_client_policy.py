
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

from leaf_common.config.resolver import Resolver

from neuro_san.internals.run_context.langchain.llms.openai_client_policy import OpenAIClientPolicy


class AzureClientPolicy(OpenAIClientPolicy):
    """
    ClientPolicy implementation for OpenAI via Azure.

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

        # Set up a resolver to use to resolve lazy imports of classes from
        # langchain_* packages to prevent installing the world.
        resolver = Resolver()

        # pylint: disable=invalid-name
        AsyncAzureOpenAI = resolver.resolve_class_in_module("AsyncAzureOpenAI",
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
