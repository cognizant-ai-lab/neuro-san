
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

from langchain_core.tools.base import BaseTool

from neuro_san.internals.run_context.langchain.core.langchain_openai_function_tool import LangChainOpenAIFunctionTool
from neuro_san.internals.run_context.langchain.tools.tool_creator import ToolCreator


class FunctionToolCreator(ToolCreator):
    """
    Creates a langchain BaseTool from a function specification: the "function"
    dictionary of an internal agent or coded tool, the function an external
    agent reports, or a shared coded tool from the toolbox.
    """

    def create(self, function_json: Dict[str, Any], name: str) -> BaseTool:
        """
        Create a function tool from a JSON specification.

        :param function_json: The function specification. None when an external agent
                    responded without reporting a function.
        :param name: The name the calling agent uses to look the tool up
        :return: The BaseTool for the specification
        :raises ValueError: When function_json is None, so that the caller's
                    invalid-function-definition handling reports it.
        """

        # In the case of external agents, if they report a name at all, they will
        # report something different that does not identify them as external.
        # Also, most internal agents do not have a name identifier on their functional
        # JSON, which is required.  Use the agent name we are using for look-up for that
        # regardless of intent.
        if function_json is None:
            # An external agent that responded without reporting a function has
            # no function_json. Raise ValueError so the external agent creator's
            # invalid-function-definition handler reports this instead of
            # the TypeError that the assignment below would otherwise raise.
            message: str = f"Could not create tool to call external agent '{name}'. Its function_json is None."
            raise ValueError(message)

        # Copy before adding the name. function_json can be a dictionary that
        # outlives this call: for a same-server external agent it is the
        # referenced network's live registry spec (AsyncDirectAgentSession
        # returns it by reference), and internal and toolbox tools funnel
        # here with their registry/toolbox entries too. Writing the lookup
        # name into it would leak this caller's reference string into that
        # shared state (issue #1230). The copy is deliberately shallow: only
        # the top-level "name" key is written here, so nested dicts stay shared.
        use_function_json: Dict[str, Any] = dict(function_json)
        use_function_json["name"] = name
        return LangChainOpenAIFunctionTool.from_function_json(use_function_json, self.tool_caller)
