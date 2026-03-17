
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
from typing import Tuple
from typing import Type

from copy import copy as shallow_copy
from logging import getLogger
from logging import Logger

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import BaseMessage

from leaf_common.config.resolver_util import ResolverUtil

from neuro_san.internals.journals.journal import Journal
# from neuro_san.internals.journals.progress_journal import ProgressJournal
from neuro_san.internals.messages.origination import Origination

# We don't want to drag in langgraph as a dependency, but we will allow Checkpointers from there.
Checkpointer: Type = Any


class MiddlewareFactory:
    """
    Creates instances of AgentMiddleware based on a list of middleware configs.
    """

    def __init__(self, origin: List[Dict[str, Any]], chat_history: List[BaseMessage], base_journal: Journal):
        """
        :param origin: A list of dictionaries containing origin information as to which agent
                    is creating the middleware.
        :param chat_history: The chat history of the RunContext that the middleware is being created for.
        :param base_journal: The base Journal for the RunContext that the middleware is being created for.
        """
        self.origin: List[Dict[str, Any]] = origin
        self.origin_str: str = Origination.get_full_name_from_origin(self.origin)
        self.chat_history: List[BaseMessage] = chat_history
        self.base_journal: Journal = base_journal
        self.instantiation_indexes: Dict[str, int] = {}
        self.logger: Logger = getLogger(self.__class__.__name__)

    def create_agent_middleware(self, config: List[Dict[str, Any]], sly_data: Dict[str, Any]) \
            -> Tuple[List[AgentMiddleware], Checkpointer]:
        """
        Create instances of AgentMiddleware based on the config.
        :param config: A list of dictionaries containing specific middleware configurations.
                    Order matters.
        :param sly_data: The private sly_data dictionary for the agent invocation
        :return: A tuple of:
                * A list of instances of AgentMiddleware.
                  Can be an empty list if there is no middleware to create.
                * A Checkpointer instance if required by the config. Can be None.
        """
        # Keep a running list of what we've created.
        checkpointer: Checkpointer = None
        all_middleware: List[AgentMiddleware] = []

        if config is None or len(config) == 0:
            # No middleware specified
            return all_middleware, checkpointer

        # Loop through the config entries.
        for middleware_index, one_config in enumerate(config):

            middleware: AgentMiddleware = None
            created_checkpointer: Checkpointer = None
            middleware, created_checkpointer = self.create_middleware(one_config, sly_data, middleware_index)
            if middleware is not None:
                all_middleware.append(middleware)

            if created_checkpointer is not None:
                if checkpointer is not None:
                    self.logger.warning("Multiple Checkpointers specified. Using the first one.")
                else:
                    checkpointer = created_checkpointer

        return all_middleware, checkpointer

    def create_middleware(self, config: Dict[str, Any], sly_data: Dict[str, Any], index: int = 0) \
            -> Tuple[AgentMiddleware, Checkpointer]:
        """
        Create an instance of AgentMiddleware based on the config.

        :param config: A dictionary containing specific middleware configurations.
        :param sly_data: The private sly_data dictionary for the agent invocation.
        :param index: The index of the middleware in the config
        :return:
                Can be None if there is no middleware to create.
        :return: A tuple of:
                * An instance of AgentMiddleware per the config.
                  Can be None if there is no middleware to create.
                * A Checkpointer instance if required by the config. Can be None.
        """
        checkpointer: Checkpointer = None
        middleware: AgentMiddleware = self.create_class("AgentMiddleware", AgentMiddleware, config, sly_data, index)

        # If needed, we could do some kind of kwargs dict here instead of a specific checkpointer arg for create_agent()
        checkpointer_config = config.get("checkpointer")
        if checkpointer_config is not None:
            checkpointer = self.create_class("Checkpointer", Checkpointer, checkpointer_config, sly_data, index)

        return middleware, checkpointer

    # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
    def create_class(self, what_we_are_creating: str, create_type: Type[Any],
                     config: Dict[str, Any], sly_data: Dict[str, Any], index: int) -> Any:
        """
        Create an instance of a class based on the config.

        :param what_we_are_creating: A string to describe what we are creating.
        :param create_type: The type of class to create.
        :param config: A dictionary containing specific class configurations.
        :param sly_data: The private sly_data dictionary for the agent invocation.
        :return: An instance of the class or None if class creation fails.
        """
        created_class: Type[create_type] = None

        error_context: str = f"{what_we_are_creating} at index {index} of {self.origin_str}"
        if not isinstance(config, Dict):
            self.logger.warning("%s is missing a configuration dictionary. Skipping it.", error_context)
            return created_class

        class_name: str = config.get("class")
        if class_name is None:
            self.logger.warning("%s is missing the 'class' field. Skipping it.", error_context)
            return created_class

        # Resolve the class
        try:
            created_class = ResolverUtil.create_class(class_name, error_context, create_type)
        except ValueError as exception:
            message = f"""
Problems loading class {class_name}: {str(exception)}

Check these things:
1. Is the class findable from what is set in your PYTHONPATH?
"""
            self.logger.error(message)
            raise ValueError(message) from exception

        # Get the instantiation index for this instance and increment for future use
        instantation_index = self.instantiation_indexes.get(class_name, 0)
        self.instantiation_indexes[class_name] = instantation_index + 1

        # Set up an origin for any journaling
        use_origin: List[Dict[str, Any]] = shallow_copy(self.origin)
        add_to_origin: Dict[str, Any] = {
            "tool": class_name,
            "instantiation_index": instantation_index
        }
        use_origin.append(add_to_origin)

        # Prepare the args for the class
        empty: Dict[str, Any] = {}
        args: Dict[str, Any] = config.get("args", empty)

        # Special args keys that have data coming in from the agent framework.
        if "origin" in args:
            args["origin"] = use_origin
        if "origin_str" in args:
            args["origin_str"] = Origination.get_full_name_from_origin(use_origin)
        if "chat_history" in args:
            args["chat_history"] = self.chat_history
        if "base_journal" in args:
            args["base_journal"] = self.base_journal
        if "sly_data" in args:
            args["sly_data"] = sly_data

        # Not yet
        # if "progress_reporter" in args:
            # DEF - this is not quite correct, but here to keep dev moving.
            # This should probably be initialized as per journal creation in
            #       LangChainRunContext.update_invocation_context() and
            #       AbstractClassActivation.__init__() for ProgressJournal
            # ... so as to get correct origin information through from use_origin.
            # args["progress_reporter"] = ProgressJournal(self.base_journal)

        # Actually create the class instance
        try:
            class_instance = created_class(**args)
        except TypeError as exception:
            message = f"""
Problems creating {what_we_are_creating} instance of {class_name}: {str(exception)}

Check these things:
1. Is the class findable from what is set in your PYTHONPATH?
2. Are the args correct?
"""
            self.logger.error(message)
            raise ValueError(message) from exception

        return class_instance
