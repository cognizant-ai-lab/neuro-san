
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

from typing_extensions import override

from neuro_san.internals.graph.activations.abstract_class_activation import AbstractClassActivation
from neuro_san.internals.interfaces.agent_tool_factory import AgentToolFactory
from neuro_san.internals.run_context.interfaces.run_context import RunContext

CREATE_RUN_CONTEXT_PATH: str = \
    "neuro_san.internals.graph.activations.abstract_class_activation.RunContextFactory.create_run_context"
GET_FULL_NAME_FROM_ORIGIN_PATH: str = \
    "neuro_san.internals.graph.activations.abstract_class_activation.Origination.get_full_name_from_origin"


class ConcreteClassActivation(AbstractClassActivation):
    """
    Concrete AbstractClassActivation for tests. Its class reference comes from the constructor.
    """
    # pylint: disable=too-many-arguments
    # pylint: disable=too-many-positional-arguments
    def __init__(self, parent_run_context: RunContext,
                 factory: AgentToolFactory,
                 args: Dict[str, Any],
                 agent_tool_spec: Dict[str, Any],
                 sly_data: Dict[str, Any],
                 class_ref: str) -> None:
        """
        Constructor

        :param parent_run_context: The parent RunContext (if any) to pass
                             down its resources to a new RunContext created by
                             this call.
        :param factory: The AgentToolFactory that creates tools
        :param args: A dictionary of the tool function arguments passed in by the LLM
        :param agent_tool_spec: The dictionary describing the JSON agent tool
                            to be used by the instance
        :param sly_data: A mapping whose keys might be referenceable by agents, but whose
                 values should not appear in agent chat text. Can be an empty dictionary.
        :param class_ref: The class reference that get_full_class_ref() returns
        """
        super().__init__(parent_run_context, factory, args, agent_tool_spec, sly_data)
        self._class_ref: str = class_ref

    @override
    def get_full_class_ref(self) -> str:
        """
        Returns the class reference given to the constructor.

        :return: The class reference string
        """
        return self._class_ref
