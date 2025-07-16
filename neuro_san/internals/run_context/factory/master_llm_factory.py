
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

from neuro_san.internals.interfaces.context_type_llm_factory import ContextTypeLlmFactory
from neuro_san.internals.run_context.langchain.llms.default_llm_factory import DefaultLlmFactory


class MasterLlmFactory:
    """
    Creates the correct kind of ContextTypeLlmFactory
    """

    @staticmethod
    def create_llm_factory(config: Dict[str, Any] = None) -> ContextTypeLlmFactory:
        """
        Creates an appropriate ContextTypeLlmFactory

        :param config: The config dictionary which may or may not contain
                       keys for the context_type and default llm_config
        :return: A ContextTypeLlmFactory appropriate for the context_type in the config.
        """

        llm_factory: ContextTypeLlmFactory = None
        context_type: str = MasterLlmFactory.get_context_type(config)

        if context_type.startswith("openai"):
            llm_factory = None
        elif context_type.startswith("langchain"):
            llm_factory = DefaultLlmFactory(config)
        else:
            # Default case
            llm_factory = DefaultLlmFactory(config)

        return llm_factory

    @staticmethod
    def get_context_type(config: Dict[str, Any]) -> str:
        """
        :param config: The config dictionary which may or may not contain
                       keys for the context_type and default llm_config
        :return: The context type for the config
        """
        empty: Dict[str, Any] = {}
        use_config: Dict[str, Any] = config
        if use_config is None:
            use_config = empty

        # Prepare for sanity in checks below
        context_type: str = use_config.get("context_type")
        if context_type is None:
            context_type = "langchain"
        context_type = context_type.lower()

        return context_type
