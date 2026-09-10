
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

from neuro_san.internals.interfaces.context_type_tracing_context_factory import ContextTypeTracingContextFactory
from neuro_san.internals.run_context.langchain.tracing.langchain_tracing_context_factory \
    import LangChainTracingContextFactory


class MasterTracingContextFactory:
    """
    Creates the correct kind of ContextTypeTracingContextFactory
    given the underlying toolkit.
    """

    @staticmethod
    def create_tracing_context_factory(config: Dict[str, Any] = None) -> ContextTypeTracingContextFactory:
        """
        Creates an appropriate ContextTypeTracingContextFactory

        :param config: The config dictionary which may or may not contain
                       keys for the context_type and default llm_config
        :param run_target: The RunTarget instance to be traced
        :return: A ContextTypeTracingContextFactory appropriate for the context_type in the config.
        """

        tracing_context_factory: ContextTypeTracingContextFactory = None
        context_type: str = MasterTracingContextFactory.get_context_type(config)

        if context_type.startswith("openai"):
            tracing_context_factory = None
        elif context_type.startswith("langchain"):
            tracing_context_factory = LangChainTracingContextFactory()
        else:
            # LangChain case
            tracing_context_factory = LangChainTracingContextFactory()

        return tracing_context_factory

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
        lower_context_type = context_type.lower()

        return lower_context_type
