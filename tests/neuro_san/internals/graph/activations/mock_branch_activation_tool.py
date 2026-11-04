
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

from neuro_san.interfaces.coded_tool import CodedTool
from neuro_san.internals.interfaces.agent_tool_factory import AgentToolFactory
from neuro_san.internals.run_context.interfaces.run_context import RunContext


class MockBranchActivationTool(CodedTool):
    """
    Mock CodedTool that takes the full BranchActivation constructor signature.
    Tests patch issubclass() so that AbstractClassActivation treats it as a BranchActivation.
    """

    def __init__(self, parent_run_context: RunContext,
                 factory: AgentToolFactory,
                 args: Dict[str, Any],
                 agent_tool_spec: Dict[str, Any],
                 sly_data: Dict[str, Any]) -> None:
        """
        Constructor. Stores the parameters so tests can check them.

        :param parent_run_context: The RunContext passed in by the activation
        :param factory: The AgentToolFactory that creates tools
        :param args: A dictionary of the tool function arguments passed in by the LLM
        :param agent_tool_spec: The dictionary describing the JSON agent tool
        :param sly_data: A dictionary of private data that does not go to the LLM
        """
        # The values have different types (RunContext, AgentToolFactory, dicts), hence Any.
        self._init_params: Dict[str, Any] = {
            "parent_run_context": parent_run_context,
            "factory": factory,
            "args": args,
            "agent_tool_spec": agent_tool_spec,
            "sly_data": sly_data
        }

    def get_init_params(self) -> Dict[str, Any]:
        """
        Gets the constructor parameters.

        :return: A dictionary of the constructor arguments, one key per argument:
                 "parent_run_context": the RunContext passed in
                 "factory": the AgentToolFactory passed in
                 "args": the dictionary of tool function arguments
                 "agent_tool_spec": the agent tool spec dictionary
                 "sly_data": the private data dictionary
        """
        return self._init_params

    @override
    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        """
        Returns a fixed result.

        :param args: A dictionary of the tool function arguments passed in by the LLM
        :param sly_data: A dictionary of private data that does not go to the LLM
        :return: The string "branch_activation_result"
        """
        return "branch_activation_result"
