
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


class ContextTypeLlmFactory:
    """
    Interface for Factory classes creating LLM BaseLanguageModels

    Most methods take a config dictionary which consists of the following keys:

        "model_name"                The name of the model.
                                    Default if not specified is "gpt-3.5-turbo"

        "temperature"               A float "temperature" value with which to
                                    initialize the chat model.  In general,
                                    higher temperatures yield more random results.
                                    Default if not specified is the provider's default.

        "prompt_token_fraction"     The fraction of total tokens (not necessarily words
                                    or letters) to use for a prompt. Each model_name
                                    has a documented number of max_tokens it can handle
                                    which is a total count of message + response tokens
                                    which goes into the calculation involved in
                                    get_max_prompt_tokens().
                                    By default the value is 0.5.

        "max_tokens"                The maximum number of tokens to use in
                                    get_max_prompt_tokens(). By default this comes from
                                    the model description in this class.
    """

    def load(self):
        """
        Goes through the process of loading any user extensions and/or configuration
        files
        """
        raise NotImplementedError

    def create_llm(self, config: Dict[str, Any], sly_data: Dict[str, Any] = None) -> Any:
        """
        Create an llm instance BaseLanguageModel from the fully-specified llm config.
        :param config: The fully specified llm config from which the LLM instance
                    should be created.
        :param sly_data: A user-provided dictionary of private data,
                from which we might extract API keys to use for user billing.
                Can be None indicating no API keys are provided at all and the system defaults will be used.
        :return: An llm instance native to the context type.
                Can raise a ValueError if the config's class or model_name value is
                unknown to this method.
                Can return None if required llm_config keys are not provided.
        """
        raise NotImplementedError
