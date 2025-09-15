
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
# Needed for method referencing different instance of the same class
# See https://stackoverflow.com/questions/33533148/how-do-i-type-hint-a-method-with-the-type-of-the-enclosing-class
from __future__ import annotations

from typing import Any
from typing import Dict
from typing import List

from langchain_core.messages.base import BaseMessage

from neuro_san.internals.interfaces.invocation_context import InvocationContext
from neuro_san.internals.journals.journal import Journal
from neuro_san.internals.run_context.interfaces.agent_spec_provider import AgentSpecProvider
from neuro_san.internals.run_context.interfaces.run import Run


class RunContext(AgentSpecProvider):
    """
    Interface supporting high-level LLM usage.
    """

    async def create_resources(self, agent_name: str,
                               instructions: str,
                               assignments: str,
                               tool_names: List[str] = None):
        """
        Creates resources to be used during a run of an agent.
        The result is stored as a member in this instance for future use.
        :param agent_name: String name for the agent.
        :param instructions: string instructions that are used to create the agent
        :param assignments: string assignments of function parameters that are used as input
        :param tool_names: The list of registered tool names to use.
                    Default is None implying no tool is to be called.
        """
        raise NotImplementedError

    async def submit_message(self, user_message: str) -> Run:
        """
        Submits a message to create a run.
        :param user_message: The message to submit
        :return: The Run instance which is processing the agent's message
        """
        raise NotImplementedError

    async def wait_on_run(self, run: Run, journal: Journal = None) -> Run:
        """
        Loops on the given run's status for service-side processing
        to be done.
        :param run: The Run instance to wait on
        :param journal: The Journal which captures the "thinking" messages.
        :return: An potentially updated Run instance
        """
        raise NotImplementedError

    async def get_response(self) -> List[BaseMessage]:
        """
        :return: The list of messages from the instance's thread.
        """
        raise NotImplementedError

    async def submit_tool_outputs(self, run: Run, tool_outputs: List[Dict[str, Any]]) -> Run:
        """
        :param run: The Run instance handling the execution of the agent
        :param tool_outputs: The tool outputs to submit
                The component dictionaries can have the following keys:
                    "origin"        A List of origin dictionaries indicating the origin of the run.
                    "output"        A string representing the output of the tool call
                    "sly_data"      Optional sly_data dictionary that might have returned from an external tool.
                    "tool_call_id"  The string id of the tool_call being executed
        :return: A potentially updated run instance handle
        """
        raise NotImplementedError

    async def delete_resources(self, parent_run_context: RunContext = None):
        """
        Cleans up the service-side resources associated with this instance
        :param parent_run_context: A parent RunContext perhaps the same instance,
                        but perhaps not.  Default is None
        """
        raise NotImplementedError

    def get_agent_tool_spec(self) -> Dict[str, Any]:
        """
        :return: the dictionary describing the data-driven agent
        """
        raise NotImplementedError

    def get_invocation_context(self) -> InvocationContext:
        """
        :return: The InvocationContext policy container that pertains to the invocation
                    of the agent.
        """
        raise NotImplementedError

    def get_chat_context(self) -> Dict[str, Any]:
        """
        :return: A ChatContext dictionary that contains all the state necessary
                to carry on a previous conversation, possibly from a different server.
                Can be None when a new conversation has been started.
        """
        raise NotImplementedError

    def get_origin(self) -> List[Dict[str, Any]]:
        """
        :return: A List of origin dictionaries indicating the origin of the run.
                The origin can be considered a path to the original call to the front-man.
                Origin dictionaries themselves each have the following keys:
                    "tool"                  The string name of the tool in the spec
                    "instantiation_index"   An integer indicating which incarnation
                                            of the tool is being dealt with.
        """
        raise NotImplementedError

    def update_invocation_context(self, invocation_context: InvocationContext):
        """
        Update internal state based on the InvocationContext instance passed in.
        :param invocation_context: The context policy container that pertains to the invocation
        """
        raise NotImplementedError

    def get_journal(self) -> Journal:
        """
        :return: The Journal associated with the instance
        """
        raise NotImplementedError
