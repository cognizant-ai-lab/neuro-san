
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


class FailingTool(CodedTool):
    """
    Mock CodedTool whose async_invoke() raises an exception.
    """

    @override
    async def async_invoke(self, args: Dict[str, Any], sly_data: Dict[str, Any]) -> Any:
        """
        Raises RuntimeError.

        :param args: A dictionary of the tool function arguments passed in by the LLM
        :param sly_data: A dictionary of private data that does not go to the LLM
        :raises RuntimeError: Always
        """
        raise RuntimeError("Tool failed")
