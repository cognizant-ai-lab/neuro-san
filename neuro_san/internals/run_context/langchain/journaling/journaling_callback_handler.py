
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
from collections.abc import Sequence
from typing import Any
from typing import Dict
from typing import List

from pydantic import ConfigDict

from langchain_core.agents import AgentAction
from langchain_core.agents import AgentFinish
from langchain_core.callbacks.base import AsyncCallbackHandler
from langchain_core.documents import Document
from langchain_core.messages.ai import AIMessage
from langchain_core.messages.base import BaseMessage
from langchain_core.outputs import LLMResult
from langchain_core.outputs.chat_generation import ChatGeneration

from neuro_san.internals.journals.journal import Journal
from neuro_san.internals.journals.originating_journal import OriginatingJournal
from neuro_san.internals.messages.origination import Origination
from neuro_san.internals.messages.agent_message import AgentMessage


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
            base_journal: Journal,
            calling_agent_journal: Journal,
            parent_origin: List[Dict[str, Any]],
            origination: Origination
    ):
        """
        Constructor

        :param base_journal: The Journal instance that allows message reporting during the course of the AgentSession.
            This is used to construct the langchain_tool_journal.
        :param calling_agent_journal: The journal of the calling agent
        :param parent_origin: A List of origin dictionaries indicating the origin of the run
            This is used to construct the langchain_tool_journal.
        :param origination: The Origination instance carrying state about tool instantation
            during the course of the AgentSession. This is used to construct the langchain_tool_journal.
        """
        self.base_journal: Journal = base_journal
        self.calling_agent_journal: Journal = calling_agent_journal
        self.parent_origin: List[Dict[str, Any]] = parent_origin
        self.origination: Origination = origination
        self.langchain_tool_journal: Journal = None

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

    async def on_tool_start(
        self,
        serialized: Dict[str, Any],
        input_str: str,
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
        :param tags: List of tags associated with the tool. Used to determine whether it is a LangChain tool.
        :param inputs: Structured dictionary of input arguments
            passed to the tool.
        """

        if "langchain_tool" in tags:

            # Extract tool name from the serialized data
            agent_name: str = serialized.get("name")

            # Build the origin path
            origin: List[Dict[str, Any]] = self.origination.add_spec_name_to_origin(self.parent_origin, agent_name)
            full_name: str = self.origination.get_full_name_from_origin(origin)

            # Combine the original tool inputs with origin metadata
            combined_args: Dict[str, Any] = inputs.copy()
            combined_args["origin"] = origin
            combined_args["origin_str"] = full_name

            # Create a journal entry for this invocation and log the combined inputs
            self.langchain_tool_journal = OriginatingJournal(self.base_journal, origin)
            message: BaseMessage = AgentMessage(content=f"Received arguments {combined_args}")
            await self.langchain_tool_journal.write_message(message)

    async def on_tool_end(self, output: Any, tags: List[str] = None, **kwargs: Any) -> None:
        """
        Callback triggered when a tool finishes execution.

        If the tool is identified as a LangChain tool (via the "langchain_tool" tag),
        this method logs the tool's output to both the calling agent's journal and the
        LangChain tool's specific journal.

        :param output: The result produced by the tool after execution.
        :param tags: List of tags associated with the tool. Used to determine whether it is a LangChain tool.
        """

        if "langchain_tool" in tags:
            # Log the tool output to the calling agent's journal
            await self.calling_agent_journal.write_message(AIMessage(content=output))

            # Also log the tool output to the LangChain tool-specific journal
            message: BaseMessage = AgentMessage(content=f"Got result: {output}")
            await self.langchain_tool_journal.write_message(message)

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
