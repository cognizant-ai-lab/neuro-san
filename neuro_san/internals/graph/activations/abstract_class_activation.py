
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
from typing import Type
from typing import Union

from asyncio import AbstractEventLoop

from copy import deepcopy
from logging import getLogger
from logging import Logger
import traceback

from langchain_core.messages.ai import AIMessage
from langchain_core.messages.base import BaseMessage

from leaf_common.asyncio.asyncio_executor import AsyncioExecutor
from leaf_common.config.resolver import Resolver
from leaf_common.config.resolver_util import ResolverUtil
from leaf_common.parsers.dictionary_extractor import DictionaryExtractor

from neuro_san.interfaces.coded_tool import CodedTool
from neuro_san.interfaces.reservationist import Reservationist
from neuro_san.internals.graph.activations.abstract_callable_activation import AbstractCallableActivation
from neuro_san.internals.graph.activations.branch_activation import BranchActivation
from neuro_san.internals.graph.interfaces.agent_tool_factory import AgentToolFactory
from neuro_san.internals.interfaces.invocation_context import InvocationContext
from neuro_san.internals.journals.journal import Journal
from neuro_san.internals.journals.progress_journal import ProgressJournal
from neuro_san.internals.journals.tool_argument_reporting import ToolArgumentReporting
from neuro_san.internals.messages.agent_message import AgentMessage
from neuro_san.internals.messages.origination import Origination
from neuro_san.internals.reservations.accumulating_agent_reservationist import AccumulatingAgentReservationist
from neuro_san.internals.run_context.factory.run_context_factory import RunContextFactory
from neuro_san.internals.run_context.interfaces.run_context import RunContext


class AbstractClassActivation(AbstractCallableActivation):
    """
    CallableActivation which can invoke a CodedTool by its class name.

    This is a base class for tools that dynamically invoke a Python class based on a
    fully qualified class reference. Subclasses must implement "get_full_class_ref"
    method to determine the target class.

    There are two main subclasses:
    - ClassActivation: retrieves the class reference directly from the tool specification.
    - ToolboxActivation: looks up the class reference from a predefined toolbox.
    """

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def __init__(self, parent_run_context: RunContext,
                 factory: AgentToolFactory,
                 arguments: Dict[str, Any],
                 agent_tool_spec: Dict[str, Any],
                 sly_data: Dict[str, Any]):
        """
        Constructor

        :param parent_run_context: The parent RunContext (if any) to pass
                             down its resources to a new RunContext created by
                             this call.
        :param factory: The AgentToolFactory used to create tools
        :param arguments: A dictionary of the tool function arguments passed in by the LLM
        :param agent_tool_spec: The dictionary describing the JSON agent tool
                            to be used by the instance
        :param sly_data: A mapping whose keys might be referenceable by agents, but whose
                 values should not appear in agent chat text. Can be an empty dictionary.
                 This gets passed along as a distinct argument to the referenced python class's
                 invoke() method.
        """
        super().__init__(factory, agent_tool_spec, sly_data)
        self.run_context: RunContext = RunContextFactory.create_run_context(parent_run_context, self)
        self.journal: Journal = self.run_context.get_journal()
        self.full_name: str = Origination.get_full_name_from_origin(self.run_context.get_origin())
        self.logger: Logger = getLogger(self.full_name)

        # One of these per CodedTool
        self.reservationist: Reservationist = None

        # See if we should be doing anything with Reservationists at all
        spec_extractor = DictionaryExtractor(self.agent_tool_spec)
        if spec_extractor.get("allow.reservations"):
            invocation_context: InvocationContext = self.run_context.get_invocation_context()
            real_reservationist: Reservationist = invocation_context.get_reservationist()
            if real_reservationist is not None:
                self.reservationist = AccumulatingAgentReservationist(real_reservationist, self.full_name)

        # Put together the arguments to pass to the CodedTool
        self.arguments: Dict[str, Any] = {}
        if arguments is not None:
            self.arguments = arguments

        # Set some standard args so CodedTool can know about origin, but only if they are
        # not already set by other infrastructure.
        if self.arguments.get("origin") is None:
            self.arguments["origin"] = deepcopy(self.run_context.get_origin())
        if self.arguments.get("origin_str") is None:
            self.arguments["origin_str"] = self.full_name

        # Set some standard args that are policy objects for CodedTool consumption.
        # If you are adding keys to this section, be sure you also add to the list
        # in ToolArgumentReporting so args messages can be properly serialized.
        if self.arguments.get("progress_reporter") is None:
            self.arguments["progress_reporter"] = ProgressJournal(self.journal)
        if self.arguments.get("reservationist") is None and self.reservationist:
            # This is the Reservationist we pass into the CodedTool.
            # You might think this belongs in sly_data, but sly_data is actually a global
            # available to all CodedTools and this Reservationist is particular to the
            # CodedTool, so it goes in the arguments.
            # We specifically give the CodedTools the accumulating version so they
            # do not have any access to service internals.
            self.arguments["reservationist"] = self.reservationist

    def get_full_class_ref(self) -> str:
        """
        Returns the full class reference path of the target tool to be invoked.

        This method must be implemented by subclasses to provide the fully qualified
        class name (e.g., "my_module.MyToolClass") of the CodedTool that should
        be instantiated and invoked. This string will be used for dynamic instantiation
        of the tool class.

        :return: A dot-separated string representing the full class path.
        """
        raise NotImplementedError

    async def build(self) -> BaseMessage:
        """
        Main entry point to the class.

        :return: A BaseMessage produced during this process.
        """
        message: BaseMessage = None

        full_class_ref: str = self.get_full_class_ref()
        self.logger.info("Calling class %s", full_class_ref)
        class_split: List[str] = full_class_ref.split(".")
        class_name: str = class_split[-1]
        # Remove the class name from the end to get the module name
        module_name: str = full_class_ref[:-len(class_name)]
        # Remove any trailing .s
        while module_name.endswith("."):
            module_name = module_name[:-1]

        # Resolve the class and the method
        python_class: Type[Any] = self.resolve_class(class_name, module_name)

        # Instantiate the CodedTool
        coded_tool: CodedTool = self.instantiate_coded_tool(python_class)

        if isinstance(coded_tool, CodedTool):
            # Invoke the CodedTool
            retval: Any = await self.attempt_invoke(coded_tool, self.arguments, self.sly_data)
        else:
            retval = f"Error: {full_class_ref} is not a CodedTool"

        # Change the result into a message
        retval_str: str = f"{retval}"
        message = AIMessage(content=retval_str)

        return message

    def resolve_class(self, class_name: str, module_name: str):
        """
        Resolve the class by trying progressively higher levels in the agent network hierarchy.

        :param class_name: The name of the class to resolve
        :param module_name: The module name containing the class
        :return: The resolved Python class
        """
        # "this_agent_tool_path" is the root path from AGENT_TOOL_PATH plus the agent network name.
        this_agent_tool_path: str = self.factory.get_agent_tool_path()
        agent_network_name: str = self.factory.agent_network.get_network_name()
        agent_network_name_parts: List[str] = agent_network_name.split("/")
        this_agent_tool_path_parts: List[str] = this_agent_tool_path.split(".")

        python_class: Type[Any] = None
        last_exception: Union[ValueError, AttributeError] = None

        self.logger.debug("Attempting to resolve class `%s` in module `%s`", class_name, module_name)

        try:
            python_class = self._attempt_resolve(
                class_name, module_name, this_agent_tool_path, this_agent_tool_path_parts, agent_network_name_parts
            )
        except (ValueError, AttributeError) as exception:
            last_exception: Union[ValueError, AttributeError] = exception

        if python_class is not None:
            self.logger.debug("Successfully resolved class `%s` in module `%s`", class_name, module_name)
            return python_class

        # If we exhausted all levels without success, warn and raise an error
        agent_name: str = self.factory.get_name_from_spec(self.agent_tool_spec)
        agent_tool_path: str = ".".join(this_agent_tool_path_parts[:-len(agent_network_name_parts)])
        message = f"""
Could not find class "{class_name}"
in module "{module_name}"
under AGENT_TOOL_PATH "{agent_tool_path}"
for the agent called "{agent_name}"
in the agent network "{agent_network_name}".

Check these things:
1.  Is there a typo in your AGENT_TOOL_PATH?
2.  Expected to find a specific CodedTool for the given agent network in:
    <AGENT_TOOL_PATH>/<agent_network>/<coded_tool_name>.py
    Global CodedTools (shared across networks) should be located at:
    <AGENT_TOOL_PATH>/<coded_tool_name>.py
    a)  Does your AGENT_TOOL_PATH point to the correct directory?
    b)  Does your CodedTool actually live in a module appropriately
        named for your agent network?
    c)  Does the module in the "class" designation for the agent {agent_name}
        match what is in the filesystem?
    d)  Does the specified class name match what is actually implemented in the file?
    e)  If an agent network contains both specific and global CodedTools,
        the global module must not have the same name as the agent network.
3. Is AGENT_TOOL_PATH findable from what is set for your PYTHONPATH?
"""
        self.logger.error(message)
        raise ValueError(message) from last_exception

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def _attempt_resolve(self, class_name: str, module_name: str,
                         this_agent_tool_path: str,
                         this_agent_tool_path_parts: List[str],
                         agent_network_name_parts: List[str]) -> Type[Any]:
        """
        Try to resolve the class through progressive resolution strategies.

        :param class_name: The name of the class to resolve
        :param module_name: The module name containing the class
        :param this_agent_tool_path: The root path from AGENT_TOOL_PATH plus the agent network name
        :param this_agent_tool_path_parts: The agent tool path split into parts
        :param agent_network_name_parts: The agent network name split into parts
        :return: The resolved Python class
        """
        # Phase 1 - Try the simplest thing first - a direct import from a fully-qualified path
        fully_qualified_name: str = f"{module_name}.{class_name}"
        python_class: Type[Any] = ResolverUtil.create_type(fully_qualified_name, raise_if_not_found=False)
        if python_class is not None:
            return python_class

        # Phase 2 - Try resolving from most specific to most general (root level)
        last_exception: Union[ValueError, AttributeError] = None
        for i in range(len(agent_network_name_parts) + 1):
            if i == 0:
                # First attempt: try the most specific path
                packages: List[str] = [this_agent_tool_path]
            else:
                # Subsequent attempts: remove one level at a time from the end
                path_parts: List[str] = this_agent_tool_path_parts[:-i]
                current_path: str = ".".join(path_parts)
                packages = [current_path]

            resolver = Resolver(packages)

            try:
                python_class = resolver.resolve_class_in_module(class_name, module_name)
                if python_class is not None:
                    return python_class
            # The Resolver internally catches ImportError (and SyntaxError, etc.) in try_to_import_module()
            # and converts them into messages. What it raises outward is:
            # ValueError — when the module can't be found at all
            # AttributeError — from getattr(found_module, class_name) when the module was found
            # but the class doesn't exist in it
            except (ValueError, AttributeError) as exception:
                last_exception = exception

        # Re-raise the last exception so the caller knows resolution failed
        if last_exception is not None:
            raise last_exception

        raise ValueError(f'Could not resolve class "{class_name}" in module "{module_name}".')

    def instantiate_coded_tool(self, python_class) -> CodedTool:
        """
        Instantiate the CodedTool from the resolved class.

        :param python_class: The Python class to instantiate
        :return: An instance of the CodedTool
        """
        coded_tool: CodedTool = None
        try:
            if issubclass(python_class, BranchActivation):
                # Allow for a combination of BranchActivation + CodedTool to allow
                # for easier invocation of agents within code.
                coded_tool = python_class(self.run_context, self.factory,
                                          self.arguments, self.agent_tool_spec, self.sly_data)
            else:
                # Go with the no-args constructor as per the run-of-the-mill contract
                coded_tool = python_class()
        except TypeError as exception:
            message: str = f"""
Coded tool class {python_class} must take no arguments to its constructor.
The standard pattern for CodedTools is to not have a constructor at all.

Some hints:
1)  If you are attempting to re-use/re-purpose your CodedTool implementation,
    consider adding an "args" block to your specific agents. This will pass
    whatever dictionary you specify there as extra key/value pairs to your
    CodedTool's invoke()/async_invoke() method's args parameter in addition
    to those provided by any calling LLM.
2)  If you need something more dynamic that is shared amongst the CodedTools
    of your agent network to handle a single request, consider lazy instantiation
    of the object in question, and share a reference to that object in the
    sly_data dictionary. The lifetime of that object will last as long
    as the request itself is in motion.
3)  Try very very hard to *not* use global variables/singletons to bypass this limitation.
    Your CodedTool implementation is working in a multi-threaded, asynchronous
    environment. If your first instinct is to reach for a global variable,
    you are highly likely to diminish the performance for all other requests
    on any server running your agent with your CodedTool.
"""
            raise TypeError(message) from exception

        return coded_tool

    async def attempt_invoke(self, coded_tool: CodedTool, arguments: Dict[str, Any], sly_data: Dict[str, Any]) \
            -> Any:
        """
        Attempt to invoke the coded tool.

        :param coded_tool: The CodedTool instance to invoke
        :param arguments: The arguments dictionary to pass as input to the coded_tool
        :param sly_data: The sly_data dictionary to pass as input to the coded_tool
        :return: The result of the coded_tool, whatever that is.
        """
        retval: Any = None

        arguments_dict: Dict[str, Any] = ToolArgumentReporting.prepare_tool_start_dict(arguments)
        message = AgentMessage(content="Received arguments:", structure=arguments_dict)
        await self.journal.write_message(message)

        try:
            tool_error: bool = False
            try:
                # Try the preferred async method
                retval = await coded_tool.async_invoke(self.arguments, self.sly_data)

            except NotImplementedError:
                # That didn't work, so try running the synchronous method as an async task
                # within the confines of the proper executor.
                # Warn that there is a better alternative
                message = f"""
Running CodedTool class {coded_tool.__class__.__name__}.invoke() synchronously in an asynchronous environment.
This can lead to performance problems when running within a server. Consider porting to the async_invoke() method.
"""
                self.logger.info(message)
                await self.journal.write_message(AgentMessage(content=message))

                # Try to run in the executor.
                invocation_context = self.run_context.get_invocation_context()
                executor: AsyncioExecutor = invocation_context.get_asyncio_executor()
                loop: AbstractEventLoop = executor.get_event_loop()
                retval = await loop.run_in_executor(None, coded_tool.invoke, arguments, sly_data)
        # pylint: disable=broad-exception-caught
        except Exception as exception:
            # There was an error invoking the CodedTool.
            # Log it and return an error string.
            tool_error = True
            retval = f"Error: {str(exception)}"
            self.logger.error("Error invoking CodedTool %s: %s", coded_tool.__class__.__name__, str(exception))
            self.logger.error(traceback.format_exc())

        retval_dict: Dict[str, Any] = {
            "tool_end": True,
            "tool_error": tool_error,
            "tool_output": retval
        }
        message = AgentMessage(content="Got result:", structure=retval_dict)
        await self.journal.write_message(message)

        return retval
