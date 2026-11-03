
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

from copy import deepcopy

from typing_extensions import override

from neuro_san.internals.run_context.langchain.tools.function_tool_creator import FunctionToolCreator


class InternalAgentToolCreator(FunctionToolCreator):
    """
    Creates the langchain BaseTool through which an agent calls an LLM agent of
    its own agent network.

    BranchActivation builds the called agent's input prompt from the call's arguments
    and its command. When the agent's function declares no parameters, the calling LLM
    would send no arguments, so the prompt would have none of the request. The tool then
    gets a single required "inquiry" string parameter.

    Only the tool gets the parameter. The agent's spec keeps no parameters, so
    BranchActivation still passes on every argument that a coded tool sends it.
    """

    # The parameters of the tool for an LLM agent whose function declares none.
    DEFAULT_PARAMETERS: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "inquiry": {
                "type": "string",
                "description": "The request to send to this agent.",
            },
        },
        "required": ["inquiry"],
    }

    @override
    def get_tool_function_json(self) -> Dict[str, Any]:
        """
        Gives the function specification that the tool is made from: the agent's own,
        or a copy with the default parameters when it declares none.

        :return: The function specification for the tool
        """
        function_json: Dict[str, Any] = super().get_tool_function_json()
        if not FunctionToolCreator.declares_no_parameters(function_json):
            return function_json

        # Change a copy, so the agent's spec keeps no parameters.
        use_function_json: Dict[str, Any] = dict(function_json)
        use_function_json["parameters"] = deepcopy(InternalAgentToolCreator.DEFAULT_PARAMETERS)
        return use_function_json
