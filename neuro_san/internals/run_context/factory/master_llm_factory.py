
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
        lower_context_type: str = context_type.lower()

        return lower_context_type
