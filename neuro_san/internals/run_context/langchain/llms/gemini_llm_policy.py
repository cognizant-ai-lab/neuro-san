
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
        # Not sure of the right way to do this for Gemini just yet.
        pass
