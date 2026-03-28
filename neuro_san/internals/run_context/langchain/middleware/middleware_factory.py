
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
from typing import Optional
from typing import Tuple
from typing import Type

from logging import getLogger
from logging import Logger

from langchain.agents.middleware.types import AgentMiddleware
from langchain_core.messages import BaseMessage

from leaf_common.config.resolver_util import ResolverUtil
from leaf_common.parsers.dictionary_extractor import DictionaryExtractor

from neuro_san.interfaces.reservationist import Reservationist
from neuro_san.internals.interfaces.invocation_context import InvocationContext
from neuro_san.internals.journals.originating_journal import OriginatingJournal
from neuro_san.internals.journals.progress_journal import ProgressJournal
from neuro_san.internals.messages.origination import Origination
from neuro_san.internals.reservations.accumulating_agent_reservationist import AccumulatingAgentReservationist

# We don't want to drag in langgraph as a dependency, but we will allow Checkpointers from there.
Checkpointer: Type = Any


class MiddlewareFactory:
    """
    Creates instances of AgentMiddleware based on a list of middleware configs.
    """

    def __init__(self, invocation_context: InvocationContext,
                 origin: List[Dict[str, Any]],
                 chat_history: List[BaseMessage]):
        """
        :param invocation_context: The invocation context for the request.
        :param origin: A list of dictionaries containing origin information as to which agent
                    is creating the middleware.
        :param chat_history: The chat history of the RunContext that the middleware is being created for.
        """
        self.invocation_context: InvocationContext = invocation_context
        self.origin: List[Dict[str, Any]] = origin
        self.chat_history: List[BaseMessage] = chat_history
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

    # pylint: disable=too-many-arguments
    # pylint: disable=too-many-positional-arguments
    def create_class(self, what_we_are_creating: str, create_type: Type[Any],
                     config: Dict[str, Any], sly_data: Dict[str, Any], index: int) -> Any:
        """
        Create an instance of a class based on the config.

        :param what_we_are_creating: A string to describe what we are creating.
        :param create_type: The type of class to create.
        :param config: A dictionary containing specific class configurations.
        :param sly_data: The private sly_data dictionary for the agent invocation.
        :param index: The index of the class in the config.
        :return: An instance of the class or None if class creation fails.
        """
        error_context: str = self._build_error_context(what_we_are_creating, index)

        class_name: str = self._get_class_name(config, error_context)
        if class_name is None:
            return None

        created_class: Type[Any] = self._resolve_class(class_name, error_context, create_type)

        middleware_origin, middleware_origin_str, reservationist = self._prepare_middleware_context(class_name, config)

        args: Dict[str, Any] = self._prepare_args(
            config, sly_data, middleware_origin, middleware_origin_str, reservationist)

        return self._instantiate_class(created_class, args, what_we_are_creating, class_name)

    def _build_error_context(self, what_we_are_creating: str, index: int) -> str:
        """Build a descriptive error context string."""
        origin_str: str = Origination.get_full_name_from_origin(self.origin)
        return f"{what_we_are_creating} at index {index} of {origin_str}"

    def _get_class_name(self, config: Dict[str, Any], error_context: str) -> Optional[str]:
        """
        Validate config and extract the class name.
        :return: The class name, or None if config is invalid.
        """
        if not isinstance(config, dict):
            self.logger.warning("%s is missing a configuration dictionary. Skipping it.", error_context)
            return None

        class_name: str = config.get("class")
        if class_name is None:
            self.logger.warning("%s is missing the 'class' field. Skipping it.", error_context)
            return None

        return class_name

    def _resolve_class(self, class_name: str, error_context: str, create_type: Type[Any]) -> Type[Any]:
        """Resolve and return the class from the class name."""
        try:
            return ResolverUtil.create_class(class_name, error_context, create_type)
        except ValueError as exception:
            message = f"""
Problems loading class {class_name}: {str(exception)}

Check these things:
1. Is the class findable from what is set in your PYTHONPATH?
"""
            self.logger.error(message)
            raise ValueError(message) from exception

    def _prepare_middleware_context(self, class_name: str, config: Dict[str, Any]) \
            -> Tuple[List[Dict[str, Any]], str, Reservationist]:
        """
        Prepare the origin and reservationist for the middleware.
        :param class_name: The class name of the middleware.
        :param config: The middleware configuration dictionary.
        :return: A tuple of (middleware_origin, middleware_origin_str, reservationist).
        """
        tool_name_for_class: str = class_name.split(".")[-1]
        origination: Origination = self.invocation_context.get_origination()
        middleware_origin: List[Dict[str, Any]] = origination.add_spec_name_to_origin(self.origin, tool_name_for_class)
        middleware_origin_str: str = Origination.get_full_name_from_origin(middleware_origin)

        reservationist: Reservationist = None
        config_extractor = DictionaryExtractor(config)
        if config_extractor.get("allow.reservations"):
            real_reservationist: Reservationist = self.invocation_context.get_reservationist()
            if real_reservationist is not None:
                reservationist = AccumulatingAgentReservationist(real_reservationist, middleware_origin_str)

        return middleware_origin, middleware_origin_str, reservationist

    def _prepare_args(self, config: Dict[str, Any], sly_data: Dict[str, Any],
                      middleware_origin: List[Dict[str, Any]],
                      middleware_origin_str: str, reservationist: Reservationist) -> Dict[str, Any]:
        """
        Prepare the args dict, injecting framework-provided values for special keys.
        """
        args: Dict[str, Any] = dict(config.get("args", {}))

        # Map of special arg keys to their framework-provided values.
        special_args: Dict[str, Any] = {
            "origin": middleware_origin,
            "origin_str": middleware_origin_str,
            "reservationist": reservationist,
            "sly_data": sly_data,
            "chat_history": self.chat_history,
        }
        for key, value in special_args.items():
            if key in args:
                args[key] = value

        # Journal-based args require lazy creation of the journal.
        if "journal" in args or "progress_reporter" in args:
            journal = OriginatingJournal(self.invocation_context.get_journal(), middleware_origin)
            if "journal" in args:
                args["journal"] = journal
            if "progress_reporter" in args:
                args["progress_reporter"] = ProgressJournal(journal)

        return args

    def _instantiate_class(self, created_class: Type[Any], args: Dict[str, Any],
                           what_we_are_creating: str, class_name: str) -> AgentMiddleware:
        """Instantiate the resolved class with the prepared args."""
        try:
            return created_class(**args)
        except TypeError as exception:
            message = f"""
Problems creating {what_we_are_creating} instance of {class_name}: {str(exception)}

Check these things:
1. Is the class findable from what is set in your PYTHONPATH?
2. Are the args correct?
"""
            self.logger.error(message)
            raise ValueError(message) from exception
