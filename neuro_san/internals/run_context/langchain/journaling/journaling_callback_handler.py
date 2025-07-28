
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

from pydantic import ConfigDict

from langchain_core.agents import AgentAction
from langchain_core.agents import AgentFinish
from langchain_core.callbacks.base import AsyncCallbackHandler
from langchain_core.documents import Document
from langchain_core.outputs import LLMResult
from langchain_core.outputs.chat_generation import ChatGeneration

from neuro_san.internals.journals.journal import Journal
from neuro_san.internals.journals.originating_journal import OriginatingJournal
from neuro_san.internals.messages.origination import Origination
from neuro_san.internals.messages.agent_message import AgentMessage
from neuro_san.internals.run_context.interfaces.run_context import RunContext


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

    def __init__(self, run_context: RunContext, journal: OriginatingJournal):
        """
        Constructor

        :param journal: The journal to write messages to
        """
        self.run_context: RunContext = run_context
        self.journal: OriginatingJournal = journal

    async def on_llm_end(self, response: LLMResult,
                         **kwargs: Any) -> None:
        # Empirically we have seen that LLMResults that come in on_llm_end() calls
        # have a generations field which is a list of lists. Inside that inner list,
        # the first object is a ChatGeneration, whose text field tends to have agent
        # thinking in it.
        print(f"\n\n{response=}\n\n")
        generations = response.generations[0]
        first_generation = generations[0]
        if isinstance(first_generation, ChatGeneration):
            content: str = first_generation.text
            if content is not None and len(content) > 0:
                print(f"\n\n{content=}\n\n")
                # Package up the thinking content as an AgentMessage to stream
                message = AgentMessage(content=content.strip())
                # Some AGENT messages that come from this source end up being dupes
                # of AI messages that can come later.
                # Use this method to put the message on hold for later comparison.
                await self.journal.write_message_if_next_not_dupe(message)

    async def on_chain_end(self, outputs: Dict[str, Any],
                           **kwargs: Any) -> None:
        # print(f"In on_chain_end() with {outputs}")
        return

    async def on_tool_start(self, serialized, input_str, *, run_id, parent_run_id = None, tags = None, metadata = None, inputs = None, **kwargs):
        print(f"\n\n{serialized=}\n\n")
        print(f"\n\n{input_str=}\n\n")
        print(f"\n\n{inputs=}\n\n")
        print(f"\n\n{kwargs=}\n\n")

    async def on_tool_end(self, output: Any,
                          **kwargs: Any) -> None:
        print(f"\n\nIn on_tool_end() with {output}\n\n")
        print(f"\n\noutput_{kwargs=}\n\n")
        print(f"\n\n{kwargs.get("name")=}\n\n")
        if isinstance(output, str):
            agent_name = kwargs.get("name")
            # 1. Get the base journal from invocation context
            base_journal: Journal = self.run_context.invocation_context.get_journal()

            # 2. Build the origin path
            parent_origin = self.run_context.get_origin()
            print(f"\n\njournal_{parent_origin=}\n\n")
            # agent_name: str = self.run_context.tool_caller.get_name()
            origination: Origination = self.run_context.invocation_context.get_origination()
            origin = origination.add_spec_name_to_origin(parent_origin, agent_name)
            print(f"\n\njournal_{origin=}\n\n")

            # # 3. Create the OriginatingJournal
            journal = OriginatingJournal(base_journal, origin)
            await journal.write_message(AgentMessage(output))

    async def on_agent_action(self, action: AgentAction,
                              **kwargs: Any) -> None:
        print(f"In on_agent_action() with {action}")
        return

    async def on_agent_finish(self, finish: AgentFinish,
                              **kwargs: Any) -> None:
        print(f"In on_agent_finish() with {finish}")
        return

    async def on_retriever_end(self, documents: Sequence[Document],
                               **kwargs: Any) -> None:
        # print(f"In on_retriever_end() with {documents}")
        return
