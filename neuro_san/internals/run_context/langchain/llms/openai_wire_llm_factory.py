
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
"""
See class comment for details.
"""

from typing import Any
from typing import Dict
from typing import Type

from langchain_core.language_models import BaseLanguageModel

from neuro_san.internals.run_context.langchain.llms.llm_policy import LlmPolicy
from neuro_san.internals.run_context.langchain.llms.openai_wire_llm_policy import OpenAiWireLlmPolicy
from neuro_san.internals.run_context.langchain.llms.standard_langchain_llm_factory \
    import StandardLangChainLlmFactory


class OpenAiWireLlmFactory(StandardLangChainLlmFactory):
    """
    LlmFactory that adds the "openai-wire" class on top of the stock ones.

    Registered from a llm_info hocon file, which is how a deployment opts in.
    There is one ready to use next to the model it registers:

        export AGENT_LLM_INFO_FILE=\
            neuro_san/internals/run_context/langchain/llms/wire/llm_info_openai_wire.hocon

    See wire/openai_wire_chat_model.md for what the class is for, what it
    gives up, and the gotchas worth knowing before using it.

    Factories are resolved by class name and instantiated with no arguments,
    so everything this adds has to be expressible in configuration. It is: the
    transport is an ordinary llm_config value. See OpenAiWireLlmPolicy.
    """

    # The stock class name table plus ours. Built once here rather than
    # mutated onto the parent's, so the parent's default stays untouched for
    # everyone else.
    EXTRA_POLICY_TYPES: Dict[str, Type[LlmPolicy]] = {
        "openai-wire": OpenAiWireLlmPolicy,
    }

    def __init__(self):
        """
        Constructor. Takes no arguments: factories named in an llm_info hocon
        file are instantiated by name, with none to give them.
        """
        super().__init__()
        self.class_to_llm_policy_type = dict(self.class_to_llm_policy_type)
        self.class_to_llm_policy_type.update(self.EXTRA_POLICY_TYPES)

    def create_base_chat_model(self, config: Dict[str, Any]) -> BaseLanguageModel:
        """
        Refuse the legacy single-model path.

        It hands back a model with no way to release what it holds, and this
        factory's models own a transport that has to be closed. Use
        create_llm_resources(), which carries the policy that closes it.

        :param config: Unused
        :return: Never returns
        """
        _ = config
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support create_base_chat_model(): its models "
            "own a transport that must be released. Use create_llm_resources() instead."
        )
