
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
import uuid

from leaf_common.parsers.field_extractor import FieldExtractor

from neuro_san.internals.graph.activations.argument_assigner import ArgumentAssigner
from neuro_san.internals.graph.activations.calling_activation import CallingActivation
from neuro_san.internals.graph.interfaces.agent_tool_factory import AgentToolFactory
from neuro_san.internals.graph.interfaces.callable_activation import CallableActivation
from neuro_san.internals.messages.role_utils import RoleUtils
from neuro_san.internals.run_context.interfaces.run import Run
from neuro_san.internals.run_context.interfaces.run_context import RunContext


class BranchActivation(CallingActivation, CallableActivation):
    """
    A CallingActivation subclass which can also be a CallableActivation.
    Thus, instances are able to be branch nodes in the tool call graph.
    Leaf nodes in the call graph are also these guys, they just happen to
    not call anyone else.
    """

    # pylint: disable=too-many-arguments, too-many-positional-arguments
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
        :param arguments: A dictionary of the tool function arguments passed in
        :param agent_tool_spec: The dictionary describing the JSON agent tool
                            to be used by the instance
        :param sly_data: A mapping whose keys might be referenceable by agents, but whose
                 values should not appear in agent chat text. Can be an empty dictionary.
        """
        super().__init__(parent_run_context, factory, agent_tool_spec, sly_data)
        self.arguments: Dict[str, Any] = arguments

    def get_assignments(self) -> str:
        """
        :return: The string prompt for assigning values to the arguments to the agent.
        """
        # Get the properties of the function
        extractor: FieldExtractor = FieldExtractor()
        empty: Dict[str, Any] = {}

        agent_spec = self.get_agent_tool_spec()

        # Properties describe the function arguments
        properties: Dict[str, Any] = extractor.get_field(agent_spec, "function.parameters.properties", empty)

        assigner = ArgumentAssigner(properties)
        assignments: List[str] = assigner.assign(self.arguments)

        # Start to build a single assignments string, with one sentence for each property
        # listed (exception for name and description).
        assignments_str: str = "\n".join(assignments)
        return assignments_str

    def get_command(self) -> str:
        """
        :return: A string describing the objective of the component.
        """
        agent_spec = self.get_agent_tool_spec()
        return agent_spec.get("command", "Perform your instructions to the best of your ability.")

    async def integrate_callable_response(self, run: Run, messages: List[Any]) -> List[Any]:
        """
        :param run: The Run for the prescriptor (if any)
        :param messages: A current list of messages for the component.
        :return: An updated list of messages after this operation is done.
                This default implementation is just a pass-through of the messages argument.
        """
        new_messages: List[Any] = messages

        callable_tool_name = self.get_callable_tool_names(self.agent_tool_spec)
        if callable_tool_name is None:
            # If there is no callable_tool_name, then there is no action from the
            # callable class to integrate
            return new_messages

        while run.requires_action():
            # The tool we just called requires more information
            new_run = await self.make_tool_function_calls(run)
            new_run = await self.run_context.wait_on_run(new_run, self.journal)
            new_messages = await self.run_context.get_response()

        return new_messages

    async def build(self) -> str:
        """
        Main entry point to the class.

        :return: A string representing a List of messages produced during this process.
        """

        assignments = self.get_assignments()
        instructions = self.get_instructions()

        uuid_str = str(uuid.uuid4())
        component_name = self.get_name()
        unique_name = f"{uuid_str}_{component_name}"
        await self.create_resources(unique_name, instructions, assignments)

        command = self.get_command()
        run: Run = await self.run_context.submit_message(command)
        run = await self.run_context.wait_on_run(run, self.journal)

        messages = await self.run_context.get_response()

        messages = await self.integrate_callable_response(run, messages)

        response = RoleUtils.generate_response(messages)
        return response

    def get_origin(self) -> List[Dict[str, Any]]:
        """
        :return: A List of origin dictionaries indicating the origin of the run.
                The origin can be considered a path to the original call to the front-man.
                Origin dictionaries themselves each have the following keys:
                    "tool"                  The string name of the tool in the spec
                    "instantiation_index"   An integer indicating which incarnation
                                            of the tool is being dealt with.
        """
        return self.run_context.get_origin()

    async def use_tool(self, tool_name: str, tool_args: Dict[str, Any], sly_data: Dict[str, Any]) -> str:
        """
        Experimental method to call a tool more directly from a subclass.

        NOTE: This method is not correctly reporting history or anything like that just yet.

        :param tool_name: The name of the tool to invoke
        :param tool_args: A dictionary of arguments to send to the tool.
        :param sly_data: private data dictionary to send to the tool.
        :return: A string representing the last received content text of the last message.
        """

        # Use the tool
        our_agent_spec = self.get_agent_tool_spec()
        callable_activation: CallableActivation = self.factory.create_agent_activation(self.run_context,
                                                                                       our_agent_spec,
                                                                                       tool_name,
                                                                                       sly_data,
                                                                                       tool_args)
        message: str = await callable_activation.build()

        # We got a list of messages back as a string. Take the last.
        message_list: List[Dict[str, Any]] = json.loads(message)
        message_dict: Dict[str, Any] = message_list[-1]
        content: str = message_dict.get("content")

        return content
