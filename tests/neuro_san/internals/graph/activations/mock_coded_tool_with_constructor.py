
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


class MockCodedToolWithConstructor(CodedTool):
    """
    Mock CodedTool whose constructor takes an argument, which AbstractClassActivation does not allow.
    """

    def __init__(self, required_arg: Any) -> None:
        """
        Constructor.

        :param required_arg: Any value. The argument only makes the constructor invalid for a CodedTool.
        """
        # Any type works: only the constructor's argument count matters.
        self.required_arg: Any = required_arg

    @override
    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        """
        Returns a fixed result. Tests do not reach this method.

        :param args: A dictionary of the tool function arguments passed in by the LLM
        :param sly_data: A dictionary of private data that does not go to the LLM
        :return: The string "should_not_reach"
        """
        return "should_not_reach"
