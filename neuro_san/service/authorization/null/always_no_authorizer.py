
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

from neuro_san.service.authorization.interfaces.abstract_authorizer import AbstractAuthorizer


class AlwaysNoAuthorizer(AbstractAuthorizer):
    """
    Implementation of the Authorizer interface that lets no requests through.
    """

    async def authorize(self, actor: Dict[str, Any], action: str, resource: Dict[str, Any]) -> bool:
        """
        :param actor: The actor dictionary with the keys "type" and "id" identifying what
                      is seeking permission.  Most often this is of the form:
                        {
                            "type": "User",
                            "id": "<username>"
                        }
        :param action:  The action for which the user is asking permission for.
                        Most often this is one of the Permission values of:
                            "create", "read", "update" or "delete".
        :param resource: The resource dictionary with the keys "type" and "id" identifying
                      just what is to be authorized for use.  For instance:
                        {
                            "type": "AgentNetwork",
                            "id": "hello_world"
                        }
        :return: True if the actor is allowed to take the requested action on the resource.
                 False otherwise.
        """
        # By default, no one can do anything
        return False

    async def grant(self, actor: Dict[str, Any], relation: str, resource: Dict[str, Any]) -> bool:
        """
        :param actor: The actor dictionary with the keys "type" and "id" identifying what
                      will be permitted.  Most often this is of the form:
                        {
                            "type": "User",
                            "id": "<username>"
                        }
        :param relation: The relation for which the user will be permitted.
                     Most often this is one of the strings from the Role enum.

        :param resource: The resource dictionary with the keys "type" and "id" identifying
                      just what is to be authorized for use.  For instance:
                        {
                            "type": "AgentNetwork",
                            "id": "hello_world"
                        }
        :return: True if the grant succeeded, False if the grant already existed.
        """
        return False

    async def revoke(self, actor: Dict[str, Any], relation: str, resource: Dict[str, Any]) -> bool:
        """
        :param actor: The actor dictionary with the keys "type" and "id" identifying what
                      will no longer be permitted.  Most often this is of the form:
                        {
                            "type": "User",
                            "id": "<username>"
                        }
        :param relation: The relation for which the user will no longer be permitted.
                     Most often this is one of the strings from the Role enum.

        :param resource: The resource dictionary with the keys "type" and "id" identifying
                      just what is to be no longer authorized for use.  For instance:
                        {
                            "type": "AgentNetwork",
                            "id": "hello_world"
                        }
        :return: True if the revoke succeeded, False if the revoke already existed.
        """
        return False

    async def list(self, actor: Dict[str, Any], relation: str, resource: Dict[str, Any]) -> List[str]:
        """
        Return a list of resource ids that the actor has the given relation to,
        as per the graph specified by the authorization model.

        :param actor: The actor dictionary with the keys "type" and "id" identifying what
                      entity's relation should be checked.  Most often this is of the form:
                        {
                            "type": "User",
                            "id": "<username>"
                        }
        :param relation: The relation for which the user's permissions will be checked.
                        Most often this is one of the Permission values of:
                            "create", "read", "update" or "delete".

        :param resource: The resource dictionary with the keys "type" and "id" identifying
                      just what is to be authorized for use.  For instance:
                        {
                            "type": "AgentNetwork",
                            # Note: "id" is not specified. We want a list of these returned.
                        }
        :return: A list of resource ids that the actor has the given relation with.
                 An empty return list implies that the actor has access to no objects
                 of the given resource type.
        """
        # Indicate no access to anything
        retval: List[str] = []
        return retval
