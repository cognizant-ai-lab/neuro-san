
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

from neuro_san.internals.interfaces.run_target import RunTarget
from neuro_san.internals.interfaces.tracing_context import TracingContext


class ContextTypeTracingContextFactory:
    """
    Interface for Factory classes creating TracingContexts for RunTargets.
    """

    def create_tracing_context(self, config: Dict[str, Any], run_target: RunTarget) -> TracingContext:
        """
        Creates a RunTarget based on another RunTarget

        :param config: The configuration for the tracing context
        :param run_target: The RunTarget instance to be traced
        :return: An appropriate TracingContext
        """
        raise NotImplementedError
