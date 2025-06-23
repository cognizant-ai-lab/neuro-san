
# Copyright (C) 2023-2025 Cognizant Digital Business, Evolutionary AI.
# All Rights Reserved.
# Issued under the Academic Public License.
#
# You can be released from the terms, and requirements of the Academic Public
# License by purchasing a commercial license.
# Purchase of a commercial license is mandatory for any use of the
# neuro-san SDK Software in commercial settings.
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
                                    Default if not specified is 0.7

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

    def load(self, agent_llm_info_file: str):
        """
        Goes through the process of loading any user extensions and/or configuration
        files

        :param agent_llm_info_file: User-specified llm info from agent network hocon
        """
        raise NotImplementedError

    def create_llm(self, config: Dict[str, Any]) -> Any:
        """
        Create an llm instance BaseLanguageModel from the fully-specified llm config.
        :param config: The fully specified llm config from which the LLM instance
                    should be created.
        :return: An llm instance native to the context type.
                Can raise a ValueError if the config's class or model_name value is
                unknown to this method.
        """
        raise NotImplementedError
