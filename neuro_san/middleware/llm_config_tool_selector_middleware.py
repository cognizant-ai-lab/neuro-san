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

    This can significantly reduce token and time costs for agent trees that were deep
    and which can be flattened. But note that these improvements come at a cost of flexibility
    in federation and less complete answers.  Completeness in answers will depend much more on
    the descriptions of the leaf agents.

    Note that the basis class from langchain does not support fallbacks, so if you specify them,
    only the first one in the list will be taken.
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

        :param activation_capsule: A helper class that encapsulates bits needed for creating model instances
                                   from a given LLM Config.
        :param llm_config: The LLM Config to use to create model instances.
        :param sly_data: A dictionary of private data that can be passed to the model factory creating the LLMs.
                        Not strictly necessary for all cases, but definitely needed for bring-your-own-key scenarios.

        ... the rest of the args come from the langchain superclass.

        :param system_prompt: The system prompt to use for selecting the tools to use.
        :param max_tools: The maximum number of tools to use.  Defaults to None, implying no limit,
                            but practically speaking most tool-using LLMs have a limit of 7-10.
        :param always_include: A list of tool names to always include. These are not subject to the max_tools limit,
                            and if you include any, you should also further limit max_tools.
        """

        if activation_capsule is None:
            raise ValueError("activation_capsule is required")

        if llm_config is None:
            raise ValueError("llm_config is required")

        use_llm_config: Dict[str, Any] = llm_config

        # The basis class does not support fallbacks, but allow for the spec to have them.
        # Just take the first one.
        fallbacks: List[Dict[str, Any]] = llm_config.get("fallbacks")
        if isinstance(fallbacks, list) and len(fallbacks) > 0:
            use_llm_config = fallbacks[0]

        model: BaseChatModel = activation_capsule.create_chat_model(use_llm_config, sly_data)
        super().__init__(model=model, system_prompt=system_prompt, max_tools=max_tools, always_include=always_include)
