
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


class ToolCall:
    """
    An interface representing a call to a tool
    """

    def get_id(self) -> str:
        """
        :return: The string id of this run
        """
        raise NotImplementedError

    def get_function_arguments(self) -> Dict[str, Any]:
        """
        :return: Returns a dictionary of the function arguments for the tool call
        """
        raise NotImplementedError

    def get_function_name(self) -> str:
        """
        :return: Returns the string name of the tool
        """
        raise NotImplementedError

    def get_invocation(self) -> str:
        """
        :return: String describing how the tool wants to be invoked.
                            Can be: "chatbot" - implies waiting for an answer.
                                    "event" - implies no answer needed
                                    None - implies chatbot
        """
        raise NotImplementedError
