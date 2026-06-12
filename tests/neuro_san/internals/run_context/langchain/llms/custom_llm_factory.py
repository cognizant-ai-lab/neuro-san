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

from typing import Dict
from typing import Type

from neuro_san.internals.run_context.langchain.llms.llm_policy import LlmPolicy
from neuro_san.internals.run_context.langchain.llms.standard_langchain_llm_factory import StandardLangChainLlmFactory
from neuro_san.internals.run_context.langchain.llms.openai_llm_policy import OpenAILlmPolicy


class CustomLlmFactory(StandardLangChainLlmFactory):
    """
    Test Factory class for LLM operations
    """

    def __init__(self):
        """
        Constructor.

        Extension constructors of te LangChainLlmFactory must take no arguments.
        """

        # The preferred way of extending the library to use your own LLM classes.
        # The idea here is that this is a table of class names -> LlmPolicy class types
        # that your factory will use.
        #
        # LlmPolicy classes allow for a few methods for control over creating and cleaning up
        # BaseLanguageModel instances over the course of their lifetime within the neuro-san system.
        #
        #   * create_llm() actually creates your BaseLanguageModel instance
        #           from a fully-specified llm config that is compiled by the system.
        #           "Fully-specified" here means that the config is a product of llm_config
        #           settings for any given agent in an agent network hocon file overlayed
        #           on top of the default settings you specify in your own llm_info.hocon file.
        #   * delete_resources() deletes any resources related to network clients that were
        #           created by create_llm(). Unfortunately, most often this involes reaching
        #           into the internals of your particular BaseLanguageModel implementation
        #           in order to shut down any network connections.  This isn't strictly required,
        #           but it's highly recommended in a server environment.
        #   * create_client() creates a network client that can be used to make requests
        #           to your LLM.  This is only required if your BaseLanguageModel implementation
        #           can take some kind of externally instantiated web client as an argument to
        #           its constructor and you care about delete_resources() cleanup.
        #
        # See neuro_san.internals.run_context.langchain.llms.llm_policy.LlmPolicy and some
        # of the base implementations near there for more details/examples.

        class_to_llm_policy_type: Dict[str, Type[LlmPolicy]] = {
            "test-openai": OpenAILlmPolicy
        }
        super().__init__(class_to_llm_policy_type)
