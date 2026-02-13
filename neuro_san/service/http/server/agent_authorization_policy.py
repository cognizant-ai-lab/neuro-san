
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
from typing import Set
from typing import Tuple

from os import environ

from neuro_san.internals.authorization.factory.authorizer_factory import AuthorizerFactory
from neuro_san.internals.authorization.interfaces.authorizer import Authorizer
from neuro_san.service.generic.async_agent_service_provider import AsyncAgentServiceProvider
from neuro_san.service.interfaces.agent_authorizer import AgentAuthorizer
from neuro_san.service.interfaces.permission import Permission


class AgentAuthorizationPolicy(AgentAuthorizer):
    """
    AgentAuthorizer implementation that uses authorization policy to answer
    questions about agents (if any authorization policy is desired at all).
    """

    def __init__(self, allowed_agents: Dict[str, AsyncAgentServiceProvider]):
        """
        Constructor

        :param allowed_agents: mapping from agent name to AsyncAgentServiceProvider
        """
        self.allowed_agents: Dict[str, AsyncAgentServiceProvider] = allowed_agents

        # Only need to get these once
        self.authorizer: Authorizer = AuthorizerFactory.create_authorizer()
        self.actor_key: str = environ.get("AGENT_AUTHORIZER_ACTOR_KEY", "User")
        self.actor_id_metadata_key: str = environ.get("AGENT_AUTHORIZER_ACTOR_ID_METADATA_KEY", "user_id")
        self.resource_key: str = environ.get("AGENT_AUTHORIZER_RESOURCE_KEY", "AgentNetwork")
        self.allow_relation: str = environ.get("AGENT_AUTHORIZER_ALLOW_RELATION", Permission.READ.value)

    async def allow_agent(self, agent_name: str, metadata: Dict[str, Any]) -> Tuple[bool, AsyncAgentServiceProvider]:
        """
        :param agent_name: name of an agent
        :return: a tuple of:
                * True if metadata says user is authrorized to route requests is allowed for this agent
                  False otherwise
                * instance of AsyncAgentService if it exists.  None otherwise
        """
        # Prepare the input for the Authorizer
        actor_id: str = metadata.get(self.actor_id_metadata_key)
        actor: Dict[str, Any] = {
            "type": self.actor_key,
            "id": actor_id
        }

        resource: Dict[str, Any] = {
            "type": self.resource_key,
            "id": agent_name
        }

        # Consult the authorizer
        is_authorized: bool = False
        async with self.authorizer as auth:
            is_authorized = await auth.authorize(actor, self.allow_relation, resource)

        # The network still needs to exist.
        service_provider: AsyncAgentServiceProvider = self.allowed_agents.get(agent_name)
        return is_authorized, service_provider

    async def list_agents(self, metadata: Dict[str, Any]) -> List[str]:
        """
        What is the list of allowed agents for this request?
        :param metadata: metadata from the request
        :return: a list of agent names allowed for this request
        """
        listed_agents: List[str] = self.allowed_agents.keys()

        # Prepare the input for the Authorizer
        actor_id: str = metadata.get(self.actor_id_metadata_key)
        actor: Dict[str, Any] = {
            "type": self.actor_key,
            "id": actor_id
        }

        resource: Dict[str, Any] = {
            "type": self.resource_key
            # Do not use "id" as a specific key, as we can list multitudes
        }

        # Call the authorizer to see what agents are allowed
        authorized_agents: List[str] = None
        async with self.authorizer as auth:
            authorized_agents = await auth.list(actor, self.allow_relation, resource)

        if authorized_agents is not None:

            # Authorizer specifically has something to say, so listen
            # by taking the intersection of what the authorizer allows and what exists

            authorized_set: Set[str] = set(authorized_agents)
            existing_set: Set[str] = set(listed_agents)
            listed_set: Set[str] = authorized_set.intersection(existing_set)
            listed_agents = list(listed_set)

        return listed_agents
