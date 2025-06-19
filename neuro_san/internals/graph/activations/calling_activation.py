
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

from leaf_common.config.dictionary_overlay import DictionaryOverlay

from neuro_san.internals.graph.activations.abstract_callable_activation import AbstractCallableActivation
from neuro_san.internals.graph.interfaces.agent_tool_factory import AgentToolFactory
from neuro_san.internals.graph.interfaces.callable_activation import CallableActivation
from neuro_san.internals.journals.journal import Journal
from neuro_san.internals.run_context.factory.run_context_factory import RunContextFactory
from neuro_san.internals.run_context.interfaces.run import Run
from neuro_san.internals.run_context.interfaces.run_context import RunContext
from neuro_san.internals.run_context.interfaces.tool_call import ToolCall
from neuro_san.internals.run_context.interfaces.tool_caller import ToolCaller
from neuro_san.internals.run_context.utils.external_agent_parsing import ExternalAgentParsing


class CallingActivation(AbstractCallableActivation, ToolCaller):
    """
    An implementation of the ToolCaller interface which actually does
    the calling of the other tools.

    Worth noting that this is used as a base implementation for:
        * BranchActivation - which can both call other tools and be called as a tool
        * FrontManActivation - which can only call other tools but has other specialized
            logic for interacting with user input, it being the root node of a tool graph.
    """

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def __init__(self, parent_run_context: RunContext,
                 factory: AgentToolFactory,
                 agent_tool_spec: Dict[str, Any],
                 sly_data: Dict[str, Any]):
        """
        Constructor

        :param parent_run_context: The parent RunContext (if any) to pass
                             down its resources to a new RunContext created by
                             this call.
        :param factory: The factory for Agent Tools.
        :param agent_tool_spec: The dictionary describing the JSON agent tool
                            to be used by the instance
        :param sly_data: A mapping whose keys might be referenceable by agents, but whose
                 values should not appear in agent chat text. Can be an empty dictionary.
        """
        super().__init__(factory, agent_tool_spec, sly_data)

        # Get the llm config as a combination of defaults from different places in the config
        agent_network_config: Dict[str, Any] = self.factory.get_config()
        spec_llm_config: Dict[str, Any] = self.agent_tool_spec.get("llm_config")
        run_context_config: Dict[str, Any] = self.prepare_run_context_config(agent_network_config,
                                                                             spec_llm_config)
        self.run_context: RunContext = RunContextFactory.create_run_context(parent_run_context, self,
                                                                            config=run_context_config)
        self.journal: Journal = self.run_context.get_journal()

    @staticmethod
    def prepare_run_context_config(agent_network_config: Dict[str, Any],
                                   spec_llm_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Get the llm config as a combination of defaults from different places in the config

        :param agent_network_config: The entirety of the agent network's config
        :param spec_llm_config: The llm config for the agent spec
        :return: A merged llm config to use for a RunContext
        """
        empty: Dict[str, Any] = {}
        if spec_llm_config is None:
            spec_llm_config = empty

        overlayer = DictionaryOverlay()
        llm_config = agent_network_config.get("llm_config", empty)
        llm_config = overlayer.overlay(llm_config, spec_llm_config)
        if len(llm_config.keys()) == 0:
            llm_config = None

        run_context_config: Dict[str, Any] = {
            "context_type": agent_network_config.get("context_type"),
            "llm_config": llm_config
        }
        return run_context_config

    def get_instructions(self) -> str:
        """
        :return: The string prompt for framing the problem in terms of purpose.
        """
        instructions: str = self.agent_tool_spec.get("instructions")
        if instructions is None:
            agent_name: str = self.get_name()
            message: str = f"""
The agent named "{agent_name}" has no instructions specified for it.

Every agent must have instructions providing the natural-language
context with which it will proces input, essentially telling it what to do.
"""
            raise ValueError(message)
        return instructions

    async def create_resources(self, component_name: str = None,
                               instructions: str = None,
                               assignments: str = ""):
        """
        Creates resources that will be used throughout the lifetime of the component.
        :param component_name: Optional string for labelling the component.
                        Defaults to the agent name if not set.
        :param instructions: Optional string for setting more fine-grained instructions.
                        Defaults to agent instructions if not set.
        :param assignments: Optional string for assigning agent functional arguments.
                        Defaults to an empty string if not set.
        """
        name = component_name
        if name is None:
            name = self.get_name()

        use_instructions = instructions
        if instructions is None:
            use_instructions = self.get_instructions()

        tool_names: List[str] = self.get_callable_tool_names(self.agent_tool_spec)
        await self.run_context.create_resources(name, use_instructions, assignments, tool_names=tool_names)

    @staticmethod
    def get_callable_tool_names(agent_tool_spec: Dict[str, Any]) -> List[str]:
        """
        :return: The names of the callable tools this instance will call
                 Can return None if the instance will not call any tools.
        """
        tool_list: List[str] = agent_tool_spec.get("tools")
        if tool_list is None or len(tool_list) == 0:
            # We really don't have any callable tools
            return None

        return tool_list

    def get_callable_tool_dict(self) -> Dict[str, str]:
        """
        :return: A dictionary of name -> name, where the keys are what the tool has been
                called in the framework (e.g. langchain) and the value is what the tool
                has been called in the agent_spec itself.  This is often a reflexive
                mapping, except in the case of external tools where a safer name is
                needed for internal framework reference.
        """
        tool_dict: Dict[str, str] = {}

        tool_list: List[str] = self.get_callable_tool_names(self.agent_tool_spec)
        if tool_list is None:
            return tool_dict

        for tool in tool_list:
            safe_name: str = ExternalAgentParsing.get_safe_agent_name(tool)
            tool_dict[safe_name] = tool

        return tool_dict

    async def make_tool_function_calls(self, component_run: Run) -> Run:
        """
        Calls all of the callable_components' functions

        :param component_run: The Run which the component is operating under
        :return: A potentially updated Run for the component
        """
        # DEF: Still a mystery as to how to get langchain implementation
        #      to tell us the tool calls it *needs* to make vs the tool calls
        #      it *could* make.
        component_tool_calls: List[ToolCall] = component_run.get_tool_calls()
        tool_outputs: List[Dict[str, Any]] = []  # Initialize an empty list to store tool outputs

        # Call each of the the listed tools and collect the results
        # of their function(s).
        for component_tool_call in component_tool_calls:

            tool_output: Dict[str, Any] = await self.make_one_tool_function_call(component_tool_call)

            # Add the tool output for the current component_tool_call to the list
            tool_outputs.append(tool_output)

        # Submit all tool outputs at once after the loop has gathered all
        # outputs of all CallableActivation' functions.
        component_run = await self.run_context.submit_tool_outputs(component_run, tool_outputs)

        return component_run

    async def make_one_tool_function_call(self, component_tool_call: ToolCall) -> Dict[str, Any]:
        """
        Calls a single callable_component's function

        :param component_tool_call: A ToolCall instance to get the function
                            arguments from
        :return: A dictionary with keys:
                "tool_call_id" a string id representing the call to the tool itself
                "output" a JSON string representing the output of the tool's function
        """
        # Get the function args as a dictionary
        tool_name: str = component_tool_call.get_function_name()
        tool_arguments: Dict[str, Any] = component_tool_call.get_function_arguments()

        # Create a new instance of a JSON-speced tool using the supplied callable_tool_name.
        # At this point tool_name might be an internal reference to an external tool,
        # so we need to check a mapping.
        callable_tool_dict: Dict[str, str] = self.get_callable_tool_dict()
        use_tool_name: str = callable_tool_dict.get(tool_name)
        if use_tool_name is None:
            raise ValueError(f"{tool_name} is not in tools {list(callable_tool_dict.keys())}")

        # Note: This is not a BaseTool. This is our own construct within graph
        #       that we can build().
        our_agent_spec = self.get_agent_tool_spec()
        callable_component: CallableActivation = \
            self.factory.create_agent_activation(self.run_context, our_agent_spec, use_tool_name,
                                                 self.sly_data, tool_arguments)

        output: str = await callable_component.build()
        # Convert to string again in case output has JSON in it. (?)
        output = json.dumps(output)

        # Prepare the tool output
        tool_output: Dict[str, Any] = {
            "origin": callable_component.get_origin(),
            "tool_call_id": component_tool_call.get_id(),
            "output": output,
            # Add the component's sly_data to the mix.
            # External tools have separate dictionaries of redacted sly_data that need to
            # be reintegrated with the single copy that floats around the agent network.
            "sly_data": callable_component.sly_data
        }

        # Clean up after this CallableActivation.
        # Note that the run_context passed here is used as a comparison to be sure
        # that the CallableActivation's cleanup does not accidentally clean up
        # any resources that should still remain open for this
        # CallingActivation's purposes.
        await callable_component.delete_resources(self.run_context)

        return tool_output

    async def build(self) -> str:
        """
        Main entry point to the class.

        :return: A string representing a List of messages produced during this process.
        """
        raise NotImplementedError
