
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
from typing import List
from typing import Tuple

# DEF - tangle to be resolved later
from neuro_san.service.generic.async_agent_service_provider import AsyncAgentServiceProvider


class AgentAuthorizer:
    """
    Interface for authorizing agent specifics given metadata from a request.
    """

    async def allow_agent(self, agent_name: str, metadata: Dict[str, Any]) -> Tuple[bool, AsyncAgentServiceProvider]:
        """
        Is the request allowed for this agent?

        :param agent_name: name of an agent
        :param metadata: metadata from the request
        :return: a tuple of:
                * True if metadata says user is authrorized to route requests is allowed for this agent
                  False otherwise
                * instance of AsyncAgentService if it exists.  None otherwise
        """
        raise NotImplementedError

    async def list_agents(self, metadata: Dict[str, Any]) -> List[str]:
        """
        What is the list of allowed agents for this request?
        :param metadata: metadata from the request
        :return: a list of agent names allowed for this request
        """
        raise NotImplementedError
