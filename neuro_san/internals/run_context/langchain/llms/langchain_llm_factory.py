
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

from langchain_core.language_models.base import BaseLanguageModel

from neuro_san.internals.interfaces.environment_configuration import EnvironmentConfiguration
from neuro_san.internals.run_context.langchain.llms.langchain_llm_resources import LangChainLlmResources


class LangChainLlmFactory(EnvironmentConfiguration):
    """
    Interface for Factory classes creating LLM BaseLanguageModels.
    This derives from EnvironmentConfiguration in order to support easy access to
    the get_value_or_env() method.

    Most methods take a config dictionary which consists of the following keys:

        "model_name"                The name of the model.
                                    Default if not specified is "gpt-3.5-turbo"

        "temperature"               A float "temperature" value with which to
                                    initialize the chat model.  In general,
                                    higher temperatures yield more random results.
                                    Default if not specified is the provider's default.

        "max_tokens"                The maximum number of tokens to use in
                                    get_max_prompt_tokens(). By default this comes from
                                    the model description in this class.
    """

    def create_base_chat_model(self, config: Dict[str, Any]) -> BaseLanguageModel:
        """
        Create a LangChainLlmResources instance from the fully-specified llm config.

        This method is provided for backwards compatibility.
        Prefer create_llm_resources() instead,
        as this allows server infrastructure to better account for outstanding
        connections to LLM providers when connections drop.

        :param config: The fully specified llm config which is a product of
                    _create_full_llm_config() above.
        :return: A BaseLanguageModel (can be Chat or LLM)
                Can raise a ValueError if the config's class or model_name value is
                unknown to this method.
        """
        raise NotImplementedError

    def create_llm_resources(self, config: Dict[str, Any]) -> LangChainLlmResources:
        """
        Create a LangChainLlmResources instance from the fully-specified llm config.

        :param config: The fully specified llm config which is a product of
                    _create_full_llm_config() above.
        :return: A LangChainLlmResources instance containing
                a BaseLanguageModel (can be Chat or LLM) and a ClientPolicy
                object that contains all related resources
                necessary for managing the model run-time lifecycle.
                Can raise a ValueError if the config's class or model_name value is
                unknown to this method.
        """
        raise NotImplementedError
