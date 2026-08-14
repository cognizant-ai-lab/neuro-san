
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
"""
Real (unmocked) langchain tool classes resolved by toolbox factory tests
through the same class paths an operator's toolbox info file would use.
"""

from typing import Any
from typing import Optional

from langchain_core.tools.base import BaseTool
from pydantic import BaseModel


class RealApiWrapper(BaseModel):
    """A real nested-arg class, standing in for an integration's API wrapper."""

    timeout: int = 10


class RealTool(BaseTool):
    """A real BaseTool subclass, standing in for an integration's tool class."""

    name: str = "real_tool"
    description: str = "A tool used to test unmocked toolbox instantiation."
    api_wrapper: Optional[RealApiWrapper] = None
    max_results: int = 5

    def _run(self, *args: Any, **kwargs: Any) -> str:
        """Minimal synchronous execution to satisfy BaseTool's interface."""
        return "ran"
