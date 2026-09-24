
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

from os import environ


class SessionUtil:
    """
    Static utility class with common session policy.
    """

    @staticmethod
    def limit_agents_list(agents_list: List[Any]) -> List[Any]:
        """
        Limit the number of agents to the value of the MAX_AGENTS_FROM_EXTERNAL_SERVER environment variable,
        if that is set. Otherwise, return the full list of agents.

        :param agents_list: List of agents
        :return: Potentially limited list of agents
        """
        use_agents_list: List[Any] = agents_list

        max_agents: int = 0
        max_agents_str: str = environ.get("MAX_AGENTS_FROM_EXTERNAL_SERVER")
        if max_agents_str is not None:
            try:
                max_agents = int(max_agents_str)
            except ValueError:
                max_agents = 0

        if max_agents > 0:
            use_agents_list = use_agents_list[:max_agents]

        return use_agents_list
