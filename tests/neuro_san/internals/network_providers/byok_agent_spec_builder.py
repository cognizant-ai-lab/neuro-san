
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

from neuro_san.internals.graph.registry.agent_network import AgentNetwork


class ByokAgentSpecBuilder:
    """
    Static-method container that builds agent network specs shaped like the ones a
    Reservationist deploys under a Bring-Your-Own-Key (BYOK) llm_config: a top-level
    llm_config whose API keys must come from sly_data, plus a top-level ("global")
    sly_data_schema that DefaultsConfigFilter is expected to merge into the front man's
    function.sly_data_schema so that clients learn they must send those keys.

    Shared by the ExpiringAgentNetworkStorage tests (write side) and the S3/local
    reservations storage tests (read side), which all check the same merge from
    different entry points.
    """

    @staticmethod
    def make_spec(front_man_name: str, front_man_schema: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Build a raw (unfiltered) two-agent network spec.

        :param front_man_name: The name of the front man agent, which is also the first tool
        :param front_man_schema: Optional sly_data_schema the front man declares on its own
                function block (e.g. http_headers for MCP servers), so tests can exercise
                the union with the global schema. None means the front man declares none.
        :return: A fresh spec dictionary whose front man has no function.sly_data_schema
                 (unless front_man_schema was given) and no per-agent llm_config.
        """
        front_man_function: Dict[str, Any] = {
            "description": "Front man that answers the user.",
            "parameters": {"type": "object", "properties": {}},
        }
        if front_man_schema is not None:
            front_man_function["sly_data_schema"] = front_man_schema
        return {
            # A second top-level default besides llm_config: DefaultsConfigFilter copies it onto
            # every agent, which is how the runtime (which reads it per agent) gets to see it.
            "max_execution_seconds": 600,
            "llm_config": {
                "fallbacks": [
                    {
                        "class": "openai",
                        "model_name": "gpt-5.2",
                        # "sly_data" means the key must arrive in sly_data.llm_config.openai_api_key
                        "openai_api_key": "sly_data",
                    }
                ]
            },
            "sly_data_schema": {
                "type": "object",
                "properties": {
                    "llm_config": {
                        "type": "object",
                        "properties": {
                            "openai_api_key": {"type": "string", "description": "The user's OpenAI API key"}
                        },
                    }
                },
                "required": ["llm_config"],
            },
            "tools": [
                {
                    "name": front_man_name,
                    "function": front_man_function,
                    "instructions": "Answer the inquiry with help from your tools.",
                    "tools": ["helper"],
                },
                {
                    "name": "helper",
                    "function": {"description": "Helps the front man."},
                    "instructions": "Help.",
                },
            ],
        }

    @staticmethod
    def front_man_spec(agent_network: AgentNetwork) -> Dict[str, Any]:
        """
        Looks up the front man's agent spec in the given network.

        :param agent_network: The AgentNetwork to inspect
        :return: The front man's agent spec dictionary exactly as held by the AgentNetwork
        """
        return agent_network.get_agent_tool_spec(agent_network.find_front_man())
