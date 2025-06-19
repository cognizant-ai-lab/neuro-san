
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
from typing import List

import json

from asyncio import AbstractEventLoop
from copy import deepcopy
from logging import getLogger
from logging import Logger

from leaf_common.asyncio.asyncio_executor import AsyncioExecutor
from leaf_common.config.resolver import Resolver

from neuro_san.interfaces.coded_tool import CodedTool
from neuro_san.internals.graph.activations.abstract_callable_activation import AbstractCallableActivation
from neuro_san.internals.graph.activations.branch_activation import BranchActivation
from neuro_san.internals.graph.interfaces.agent_tool_factory import AgentToolFactory
from neuro_san.internals.journals.journal import Journal
from neuro_san.internals.messages.agent_message import AgentMessage
from neuro_san.internals.messages.origination import Origination
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

    # pylint: disable=too-many-locals
    async def build(self) -> str:
        """
        Main entry point to the class.

        :return: A string representing a List of messages produced during this process.
        """
        messages: List[Any] = []

        full_class_ref: str = self.get_full_class_ref()
        self.logger.info("Calling class %s", full_class_ref)
        class_split = full_class_ref.split(".")
        class_name = class_split[-1]
        # Remove the class name from the end to get the module name
        module_name = full_class_ref[:-len(class_name)]
        # Remove any trailing .s
        while module_name.endswith("."):
            module_name = module_name[:-1]

        # Resolve the class and the method
        this_agent_tool_path: str = self.factory.get_agent_tool_path()
        packages: List[str] = [this_agent_tool_path]
        resolver: Resolver = Resolver(packages)

        try:
            python_class = resolver.resolve_class_in_module(class_name, module_name)
        except (ValueError, AttributeError):
            # Drop the last segment to go one level up in the module path
            parent_path: str = this_agent_tool_path.rsplit(".", 1)[0]
            packages = [parent_path]
            resolver = Resolver(packages)

            try:
                python_class = resolver.resolve_class_in_module(class_name, module_name)
            except (ValueError, AttributeError) as second_exception:
                # Get all but the last module in the path.
                # This is what was actually used for AGENT_TOOL_PATH
                agent_tool_path: str = ".".join(this_agent_tool_path.split(".")[:-1])
                agent_network: str = this_agent_tool_path.split(".")[-1]
                agent_name: str = self.factory.get_name_from_spec(self.agent_tool_spec)
                message = f"""
    Could not find class "{class_name}"
    in module "{module_name}"
    under AGENT_TOOL_PATH "{agent_tool_path}"
    for the agent called "{agent_name}"
    in the agent network "{agent_network}".

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
    """
                raise ValueError(message) from second_exception

        # Instantiate the CodedTool
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
Coded tool class {python_class} must take no orguments to its constructor.
The standard pattern for CodedTools is to not have a constructor at all.

Some hints:
1)  If you are attempting to re-use/re-purpose your CodedTool implementation,
    consider adding an "args" block to your specific agents. This will pass
    whatever dictionary you specify there as extra key/value pairs to your
    CodedTool's invoke()/async_invoke() method's args parameter in addition
    to those provided by any calling LLM.
2)  If you need something more dynamic that is shared amongst the CodedTools
    of your agent network to handle a single request, consider lazy instantiation
    of the object in question, and share a reference to that  object in the
    sly_data dictionary. The lifetime will of that object will last as long
    as the ruest itself is in motion.
3)  Try very very hard to *not* use global variables/singletons to bypass this limitation.
    Your CodedTool implementation is working in a multi-threaded, asynchronous
    environment. If your first instinct is to reach for a global variable,
    you are highly likely to diminish the performance for all other requests
    on any server running your agent with your CodedTool.
"""
            raise TypeError(message) from exception

        if isinstance(coded_tool, CodedTool):
            # Invoke the CodedTool
            retval: Any = await self.attempt_invoke(coded_tool, self.arguments, self.sly_data)
        else:
            retval = f"Error: {full_class_ref} is not a CodedTool"

        # Change the result into a message
        retval_str: str = f"{retval}"
        message: Dict[str, Any] = {
            "role": "assistant",
            "content": retval_str
        }
        messages.append(message)
        messages_str: str = json.dumps(messages)

        return messages_str

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

        message = AgentMessage(content=f"Received arguments {arguments}")
        await self.journal.write_message(message)

        try:
            # Try the preferred async_invoke()
            retval = await coded_tool.async_invoke(self.arguments, self.sly_data)
        except NotImplementedError:
            # That didn't work, so try running the synchronous method as an async task
            # within the confines of the proper executor.

            # Warn that there is a better alternative.
            message = f"""
Running CodedTool class {coded_tool.__class__.__name__}.invoke() synchronously in an asynchronous environment.
This can lead to performance problems when running within a server. Consider porting to the async_invoke() method.
"""
            self.logger.info(message)
            message = AgentMessage(content=message)
            await self.journal.write_message(message)

            # Try to run in the executor.
            invocation_context = self.run_context.get_invocation_context()
            executor: AsyncioExecutor = invocation_context.get_asyncio_executor()
            loop: AbstractEventLoop = executor.get_event_loop()
            retval = await loop.run_in_executor(None, coded_tool.invoke, arguments, sly_data)

        message = AgentMessage(content=f"Got result: {retval}")
        await self.journal.write_message(message)

        return retval
