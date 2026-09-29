
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

from os import environ

from neuro_san.internals.graph.registry.agent_network import AgentNetwork


class MissingAgentCheck:
    """
    Convience and consolidation for checks against missing/misnamed agents.
    """

    @staticmethod
    def check_agent_network(agent_network: AgentNetwork, agent_name: str) -> AgentNetwork:
        """
        :param agent_network: The AgentNetwork to check
        :param agent_name: The name of the agent to use for the session.
        :return: The AgentNetwork corresponding to the agent_name
        """

        if agent_network is None:
            manifest_file: str = environ.get("AGENT_MANIFEST_FILE")
            message = f"""
Agent named "{agent_name}" not found in manifest file: {manifest_file}.

Some things to check:
1. If the manifest file named above is None, know that the default points
   to the one provided with the neuro-san library for a smoother out-of-box
   experience.  If the agent you wanted is not part of that standard distribution,
   you need to set the AGENT_MANIFEST_FILE environment variable to point to a
   manifest.hocon file associated with your own project(s).
2. Check that the environment variable AGENT_MANIFEST_FILE is pointing to
   the manifest.hocon file that you expect and has no typos.
3. Does your manifest.hocon file contain a key for the agent specified?
4. Does the value for the key in the manifest file have a value of 'true'?
5. Does your agent name have a typo either in the hocon file or on the command line?
"""
            raise ValueError(message)

        return agent_network
