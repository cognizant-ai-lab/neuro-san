
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

from os import getenv

from neuro_san.internals.interfaces.context_type_tracing_context_factory import ContextTypeTracingContextFactory
from neuro_san.internals.interfaces.run_target import RunTarget
from neuro_san.internals.interfaces.tracing_context import TracingContext
from neuro_san.internals.run_context.langchain.tracing.langchain_tracing_context import LangChainTracingContext
from neuro_san.internals.run_context.langchain.tracing.langfuse_tracing_context import LangfuseTracingContext


class LangChainTracingContextFactory(ContextTypeTracingContextFactory):
    """
    Interface for Factory classes creating tracing contexts for RunTargets.
    """

    def create_tracing_context(self, config: Dict[str, Any], run_target: RunTarget) -> TracingContext:
        """
        Creates a RunTarget based on another RunTarget

        :param config: The configuration for the tracing context
        :param run_target: The RunTarget instance to be traced
        :return: An appropriate TracingContext
        """
        tracing_context: TracingContext = None

        test_for_langfuse: bool = getenv("LANGFUSE_ENABLED", "false").lower() == "true"

        if test_for_langfuse:
            tracing_context = LangfuseTracingContext(run_target=run_target, config=config)
        else:
            tracing_context = LangChainTracingContext(run_target=run_target, config=config)

        return tracing_context
