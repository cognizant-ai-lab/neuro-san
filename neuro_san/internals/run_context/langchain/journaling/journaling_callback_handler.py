
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
from collections.abc import Sequence
from typing import Any
from typing import Dict
from typing import List
from uuid import UUID

from pydantic import ConfigDict

from langchain_core.agents import AgentAction
from langchain_core.agents import AgentFinish
from langchain_core.callbacks.base import AsyncCallbackHandler
from langchain_core.documents import Document
from langchain_core.messages import ToolMessage
from langchain_core.messages.base import BaseMessage
from langchain_core.outputs import LLMResult
from langchain_core.outputs.chat_generation import ChatGeneration

from neuro_san.internals.journals.journal import Journal
from neuro_san.internals.journals.originating_journal import OriginatingJournal
from neuro_san.internals.journals.tool_argument_reporting import ToolArgumentReporting
from neuro_san.internals.messages.agent_message import AgentMessage
from neuro_san.internals.messages.agent_tool_result_message import AgentToolResultMessage
from neuro_san.internals.messages.origination import Origination


# pylint: disable=too-many-ancestors
class JournalingCallbackHandler(AsyncCallbackHandler):
    """
    AsyncCallbackHandler implementation that intercepts agent-level chatter

    We use this guy to intercept agent-level messages like:
        "Thought: Do I need a tool?" and preliminary results from the agent

    We are currently only listening to on_llm_end(), but there are many other
    callbacks to hook into, most of which are not really productive.
    Some are overriden here to explore, others are not.  See the base
    AsyncCallbackHandler to explore more.

    Of note: This CallbackHandler mechanism is the kind of thing that
            LoggingCallbackHandler hooks into to produce egregiously chatty logs.
    """

    # Declarations of member variables here satisfy Pydantic style,
    # which is a type validator that langchain is based on which
    # is able to use JSON schema definitions to validate fields.
    journal: OriginatingJournal

    # This guy needs to be a pydantic class and in order to have
    # a non-pydantic Journal as a member, we need to do this.
    model_config = ConfigDict(arbitrary_types_allowed=True)

    def __init__(
            self,
            calling_agent_journal: Journal,
            base_journal: Journal,
            parent_origin: List[Dict[str, Any]],
            origination: Origination
    ):
        """
        Constructor

        :param calling_agent_journal: The journal of the calling agent
        :param base_journal: The Journal instance that allows message reporting during the course of the AgentSession.
            This is used to construct the langchain_tool_journal.
        :param parent_origin: A List of origin dictionaries indicating the origin of the run
            This is used to construct the langchain_tool_journal.
        :param origination: The Origination instance carrying state about tool instantation
            during the course of the AgentSession. This is used to construct the langchain_tool_journal.
        """

        # The calling-agent journal logs the execution flow from the perspective of the agent invoking the tool
        # (e.g., MusicNerdPro). In contrast, the LangChain tool journal represents the tool's own execution
        # context—similar to how coded tools like Accountant have their own journal tied to their run context.

        # LangChain tools don’t instantiate their own RunContext, so they lack a dedicated journal by default.
        # To maintain consistency with how other tools are tracked, we explicitly create a langchain_tool_journal
        # when the tool starts. This ensures tool-specific inputs and outputs are captured independently,
        # while still allowing the calling agent to log its own perspective.

        self.calling_agent_journal: Journal = calling_agent_journal
        self.base_journal: Journal = base_journal
        self.parent_origin: List[Dict[str, Any]] = parent_origin
        self.origination: Origination = origination

        # Store per-invocation data keyed by run_id
        # This is to prevent incorrect tool names in the journals due to race condition issue.
        self._tool_journals: Dict[str, Journal] = {}
        self._tool_origins: Dict[str, List[Dict[str, Any]]] = {}

    async def on_llm_end(self, response: LLMResult,
                         **kwargs: Any) -> None:
        # Empirically we have seen that LLMResults that come in on_llm_end() calls
        # have a generations field which is a list of lists. Inside that inner list,
        # the first object is a ChatGeneration, whose text field tends to have agent
        # thinking in it.
        generations = response.generations[0]
        first_generation = generations[0]
        if isinstance(first_generation, ChatGeneration):
            content: str = first_generation.text
            if content is not None and len(content) > 0:
                # Package up the thinking content as an AgentMessage to stream
                message = AgentMessage(content=content.strip())
                # Some AGENT messages that come from this source end up being dupes
                # of AI messages that can come later.
                # Use this method to put the message on hold for later comparison.
                await self.calling_agent_journal.write_message_if_next_not_dupe(message)

    async def on_chain_end(self, outputs: Dict[str, Any],
                           **kwargs: Any) -> None:
        # print(f"In on_chain_end() with {outputs}")
        return

    # pylint: disable=too-many-arguments
    # pylint: disable=too-many-positional-arguments
    async def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
        run_id: UUID = None,
        tags: List[str] = None,
        inputs: Dict[str, Any] = None,
        **kwargs: Any
    ) -> None:
        """
        Callback triggered when a tool starts execution.

        If the tool is identified as a LangChain tool (via the "langchain_tool" tag),
        this method creates a journal entry containing the tool's input arguments,
        origin metadata, and full tool name.

        :param serialized: Serialized representation of the tool, including its name and description.
        :param input_str: String representation of the tool's input.
        :param run_id: Unique identifier for the tool execution instance.
        :param tags: List of tags associated with the tool. Used to determine whether it is a LangChain tool.
        :param inputs: Structured dictionary of input arguments
            passed to the tool.
        """

        # Extract tool name from the serialized data
        agent_name: str = serialized.get("name")
        # Remove any policy objects from the arguments passed in.
        tool_start_dict: Dict[str, Any] = ToolArgumentReporting.prepare_tool_start_dict(inputs)
        caller_structure: Dict[str, Any] = {
            "invoking_start": True,
            "invoked_agent_name": agent_name,
            "params": tool_start_dict.get("tool_args")
        }

        # Fall back to a placeholder label when the serialized tool has no name,
        # so the journaled event stays diagnostic rather than an empty "Invoking: ``".
        # The real value (or None) is still carried in invoked_agent_name above.
        display_name: str = agent_name if agent_name else "<unnamed tool>"

        # Report that we are about to invoke a tool.
        message: BaseMessage = AgentMessage(content=f"Invoking: `{display_name}` with:",
                                            structure=caller_structure)
        await self.calling_agent_journal.write_message(message)

        if "langchain_tool" in tags:

            # Build the origin path
            origin: List[Dict[str, Any]] = self.origination.add_spec_name_to_origin(self.parent_origin, agent_name)
            # Store the origin for this run_id
            self._tool_origins[run_id] = origin

            # Re-build the tool start dictionary we will report with tool origin information
            # for the langchain tool's journal.
            tool_start_dict = ToolArgumentReporting.prepare_tool_start_dict(inputs, origin)

            # Create a journal entry for this invocation and log the combined inputs
            langchain_tool_journal = OriginatingJournal(self.base_journal, origin)
            # Store the journal for this run_id
            self._tool_journals[run_id] = langchain_tool_journal
            message = AgentMessage(content="Received arguments:", structure=tool_start_dict)
            await langchain_tool_journal.write_message(message)

    async def on_tool_end(self, output: Any, run_id: UUID = None, tags: List[str] = None, **kwargs: Any) -> None:
        """
        Callback triggered when a tool finishes execution.

        If the tool is identified as a LangChain tool (via the "langchain_tool" tag),
        this method logs the tool's output to both the calling agent's journal and the
        LangChain tool's specific journal.

        :param output: The result produced by the tool after execution.
        :param run_id: Unique identifier for the tool execution instance.
        :param tags: List of tags associated with the tool. Used to determine whether it is a LangChain tool.
        """

        if "langchain_tool" in tags:
            # Log the tool output to the calling agent's journal
            # Note that output is changed to str here since it can be anything including a ToolMessage
            # If that is the case, the content is taken as the output.
            if isinstance(output, ToolMessage):
                output = output.content

            # Retrieve the correct journal and origin for this run_id
            origin = self._tool_origins.get(run_id)
            langchain_tool_journal = self._tool_journals.get(run_id)

            # Log the tool output to the calling agent's journal
            await self.calling_agent_journal.write_message(
                AgentToolResultMessage(content=str(output), tool_result_origin=origin)
            )

            # Also log the tool output to the LangChain tool-specific journal
            output_dict: Dict[str, Any] = {
                "tool_end": True,
                "tool_output": output
            }
            message: BaseMessage = AgentMessage(content="Got result:", structure=output_dict)
            await langchain_tool_journal.write_message(message)

    async def on_agent_action(self, action: AgentAction,
                              **kwargs: Any) -> None:
        # print(f"In on_agent_action() with {action}")
        return

    async def on_agent_finish(self, finish: AgentFinish,
                              **kwargs: Any) -> None:
        # print(f"In on_agent_finish() with {finish}")
        return

    async def on_retriever_end(self, documents: Sequence[Document],
                               **kwargs: Any) -> None:
        # print(f"In on_retriever_end() with {documents}")
        return
