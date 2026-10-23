
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
from typing import List

from neuro_san.internals.run_context.interfaces.tool_call import ToolCall


class Run:
    """
    An interface describing a run of an agent.
    """

    def get_id(self) -> str:
        """
        :return: The string id of this run
        """
        raise NotImplementedError

    def requires_action(self) -> bool:
        """
        :return: True if the status of the run requires external action.
                 False otherwise
        """
        raise NotImplementedError

    def get_tool_calls(self) -> List[ToolCall]:
        """
        :return: A list of ToolCalls.
        """
        raise NotImplementedError

    def model_dump_json(self) -> str:
        """
        :return: This object as a JSON string
        """
        raise NotImplementedError

    def get_tool_message(self) -> Any:
        """
        This is used when the function->tool adaptor wants to
        know what the most recent message was from the tool as
        its output.
        :return: The tool message comprising the tool output
        """
        raise NotImplementedError
