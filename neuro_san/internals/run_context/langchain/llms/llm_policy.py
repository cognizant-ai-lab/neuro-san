
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
from __future__ import annotations

from typing import Any
from typing import Dict
from typing import Tuple

from langchain_core.language_models.base import BaseLanguageModel

from leaf_common.config.resolver import Resolver

from neuro_san.internals.interfaces.environment_configuration import EnvironmentConfiguration


class LlmPolicy(EnvironmentConfiguration):
    """
    Policy interface to manage the lifecycles of web clients that talk to LLM services.
    This inherits from EnvironmentConfiguration in order to support easy access to the
    get_value_or_env() method.

    There are really two styles of implementation encompassed by this one interface.

    1) When BaseLanguageModels can have web clients passed into their constructor,
       implementations should use the create_client() method to retain any references necessary
       to help them clean up nicely in the delete_resources() method.

    2) When BaseLanguageModels cannot have web clients passed into their constructor,
       implementations should pass the already created llm into their implementation's
       constructor. Later delete_resources() implementations will need to do a reach-in
       to the llm instance to clean up any references related to the web client.

    Both of these are handled by the base implementation of create_llm_resources_components().

    LlmPolicy classes allow for a few methods for control over creating and cleaning up
    BaseLanguageModel instances over the course of their lifetime within the neuro-san system.

        * create_llm() actually creates your BaseLanguageModel instance
             from a fully-specified llm config that is compiled by the system.
             "Fully-specified" here means that the config is a product of llm_config
             settings for any given agent in an agent network hocon file overlayed
             on top of the default settings you specify in your own llm_info.hocon file.
        * delete_resources() deletes any resources related to network clients that were
             created by create_llm(). Unfortunately, most often this involes reaching
             into the internals of your particular BaseLanguageModel implementation
             in order to shut down any network connections.  This isn't strictly required,
             but it's highly recommended in a server environment.
        * create_client() creates a network client that can be used to make requests
             to your LLM.  This is only required if your BaseLanguageModel implementation
             can take some kind of externally instantiated web client as an argument to
             its constructor and you care about delete_resources() cleanup.
    """

    def __init__(self, llm: BaseLanguageModel = None):
        """
        Constructor.

        :param llm: BaseLanguageModel
        """
        self.llm: BaseLanguageModel = llm

        # Set up a resolver to use to resolve lazy imports of classes from
        # langchain_* packages to prevent installing the world.
        self.resolver: Resolver = Resolver()

    # pylint: disable=useless-return
    def create_client(self, config: Dict[str, Any]) -> Any:
        """
        Creates the web client to used by a BaseLanguageModel to be
        constructed in the future.  Neuro SAN infrastructures prefers that this
        be an asynchronous client, however we realize some BaseLanguageModels
        do not support that (even though they should!).

        Implementations should retain any references to state that needs to be cleaned up
        in the delete_resources() method.

        :param config: The fully specified llm config
        :return: The web client that accesses the LLM.
                By default this is None, as many BaseLanguageModels
                do not allow a web client to be passed in as an arg.
        """
        _ = config
        return None

    def create_llm(self, config: Dict[str, Any], model_name: str, client: Any) -> BaseLanguageModel:
        """
        Create a BaseLanguageModel instance from the fully-specified llm config
        for the llm class that the implementation supports.  Chat models are usually
        per-provider, where the specific model itself is an argument to its constructor.

        :param config: The fully specified llm config
        :param model_name: The name of the model
        :param client: The web client to use (if any)
        :return: A BaseLanguageModel (can be Chat or LLM)
        """
        raise NotImplementedError

    async def delete_resources(self):
        """
        Release the run-time resources used by the instance.

        Unfortunately for many BaseLanguageModels, this tends to involve
        a reach-in to its private internals in order to shutting down
        any web client references in there.
        """
        raise NotImplementedError

    def create_llm_resources_components(self, config: Dict[str, Any]) -> Tuple[BaseLanguageModel, LlmPolicy]:
        """
        Basic policy framework method.
        Most LLMs will not need to override this.

        :param config: The fully specified llm config
        :return: The components that go into populating an LlmResources instance.
                This is a tuple of (BaseLanguageModel, LlmPolicy).
                It's entirely fine if the LlmPolicy is not the same instance as this one.
        """
        client: Any = None
        try:
            # pylint: disable=assignment-from-none
            client = self.create_client(config)
        except NotImplementedError:
            # Slurp up the exception if nothing was implemented.
            # We will handle this in the None-client case below.
            client = None

        # Check for key "model_name", "model", and "model_id" to use as model name
        # If the config is from default_llm_info, this is always "model_name"
        # but with user-specified config, it is possible to have the other keys will be specifed instead.
        model_name: str = config.get("model_name") or config.get("model") or config.get("model_id")

        llm: BaseLanguageModel = self.create_llm(config, model_name, client)
        if client is None:
            self.llm = llm

        return llm, self
