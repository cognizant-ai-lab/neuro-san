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

from neuro_san.internals.run_context.utils.activation_capsule import ActivationCapsule


class LlmConfigToolSelectorMiddleware(LLMToolSelectorMiddleware):
    """
    LLMToolSelectorMiddleware implementation that understands neuro-san LLM Configs.

    This can significantly reduce token and time costs for agent trees that were deep
    and which can be flattened. But note that these improvements come at a cost of flexibility
    in federation and less complete answers.  Completeness in answers will depend much more on
    the descriptions of the leaf agents.

    Note: The basis for this class is the langchain implementation of LLMToolSelectorMiddleware
          and it does not take fallbacks, so we only use the first fallback in the list if
          more than one is specified.
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

        model: BaseChatModel = activation_capsule.create_chat_model(llm_config, sly_data, num_fallbacks=1)
        super().__init__(model=model, system_prompt=system_prompt, max_tools=max_tools, always_include=always_include)
