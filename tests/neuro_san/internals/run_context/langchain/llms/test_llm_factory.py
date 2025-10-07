
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

from typing import Dict
from typing import Type

from neuro_san.internals.run_context.langchain.llms.llm_policy import LlmPolicy
from neuro_san.internals.run_context.langchain.llms.standard_langchain_llm_factory import StandardLangChainLlmFactory
from neuro_san.internals.run_context.langchain.llms.openai_llm_policy import OpenAILlmPolicy


class TestLlmFactory(StandardLangChainLlmFactory):
    """
    Test Factory class for LLM operations
    """

    def __init__(self):
        """
        Constructor.

        Extension constructors of te LangChainLlmFactory must take no arguments.
        """

        class_to_llm_policy_type: Dict[str, Type[LlmPolicy]] = {
            "test-openai": OpenAILlmPolicy
        }
        super().__init__(class_to_llm_policy_type)
