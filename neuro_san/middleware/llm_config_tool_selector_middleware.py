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

from langchain.agents.middleware import LLMToolSelectorMiddleware
from langchain.agents.middleware.tool_selection import DEFAULT_SYSTEM_PROMPT
from langchain_core.language_models.chat_models import BaseChatModel

from neuro_san.internals.graph.registry.activation_capsule import ActivationCapsule


class LlmConfigToolSelectorMiddleware(LLMToolSelectorMiddleware):
    """
    LLMToolSelectorMiddleware implementation that understands neuro-san LLM Configs.
    """

    # pylint: disable=too-many-arguments
    def __init__(
                self,
                *,
                activation_capsule: ActivationCapsule,
                llm_config: Dict[str, Any],
                sly_data: Dict[str, Any] = None,
                system_prompt: str = DEFAULT_SYSTEM_PROMPT,
                max_tools: int | None = None,
                always_include: List[str] | None = None,
            ) -> None:
        """
        Constructor
        """

        if activation_capsule is None:
            raise ValueError("activation_capsule is required")

        if llm_config is None:
            raise ValueError("llm_config is required")

        model: BaseChatModel = activation_capsule.create_chat_model(llm_config, sly_data)
        print(f"Created model: {model}")
        super().__init__(model=model, system_prompt=system_prompt, max_tools=max_tools, always_include=always_include)
