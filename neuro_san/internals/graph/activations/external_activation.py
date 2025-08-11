
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
from typing import AsyncGenerator
from typing import Dict
from typing import List
from typing import Union

import json

from logging import getLogger
from logging import Logger

from leaf_common.parsers.dictionary_extractor import DictionaryExtractor

from neuro_san.interfaces.async_agent_session import AsyncAgentSession
from neuro_san.internals.graph.activations.abstract_callable_activation import AbstractCallableActivation
from neuro_san.internals.graph.activations.external_message_processor import ExternalMessageProcessor
from neuro_san.internals.graph.activations.sly_data_redactor import SlyDataRedactor
from neuro_san.internals.graph.interfaces.agent_tool_factory import AgentToolFactory
from neuro_san.internals.interfaces.async_agent_session_factory import AsyncAgentSessionFactory
from neuro_san.internals.interfaces.invocation_context import InvocationContext
from neuro_san.internals.journals.journal import Journal
from neuro_san.internals.messages.agent_message import AgentMessage
from neuro_san.internals.messages.chat_message_type import ChatMessageType
from neuro_san.internals.messages.origination import Origination
from neuro_san.internals.run_context.factory.run_context_factory import RunContextFactory
from neuro_san.internals.run_context.interfaces.run_context import RunContext
from neuro_san.message_processing.basic_message_processor import BasicMessageProcessor


# pylint: disable=too-many-instance-attributes
class ExternalActivation(AbstractCallableActivation):
    """
    CallableActivation implementation that handles using a service to call
    another agent hierarchy as a tool.
    """

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def __init__(self, parent_run_context: RunContext,
                 factory: AgentToolFactory,
                 agent_url: str,
                 arguments: Dict[str, Any],
                 sly_data: Dict[str, Any],
                 allow_from_downstream: Dict[str, Any]):
        """
        Constructor

        :param parent_run_context: The parent RunContext (if any) to pass
                             down its resources to a new RunContext created by
                             this call.
        :param factory: The factory for Agent Tools.
        :param agent_url: The string url to find the external agent.
                        Theoretically this has already been verified by use of an
                        ExternalAgentParsing method.
        :param arguments: A dictionary of the tool function arguments passed in
        :param sly_data: A mapping whose keys might be referenceable by agents, but whose
                 values should not appear in agent chat text. Can be an empty dictionary.
                 This gets passed along as a distinct argument to the referenced python class's
                 invoke() method.
        :param allow_from_downstream: A dictionary describing how to handle information
                coming in from the downstream external agent
        """
        # There is no spec on our end for the agent_tool_spec
        # Also worth noting that normally, sly_data is shared between all tools
        # but this implementation provides a security buffer for that with
        # SlyDataRedactor in multiple places.
        super().__init__(factory, None, sly_data)

        self.agent_url: str = agent_url
        self.run_context: RunContext = RunContextFactory.create_run_context(parent_run_context, self)
        self.journal: Journal = self.run_context.get_journal()
        self.arguments: Dict[str, Any] = arguments
        self.allow_from_downstream: Dict[str, Any] = allow_from_downstream

        self.session: AsyncAgentSession = None
        self.chat_context: Dict[str, Any] = None
        self.processor = BasicMessageProcessor()

        # Allow for precedence of keys from "allow.from_downstream" in the agent spec.
        extractor = DictionaryExtractor(self.allow_from_downstream)
        raw_reporting: Union[bool, str, List[str], Dict[str, Any]] = False
        for key in ["reporting", "messages"]:
            raw_reporting = extractor.get(key, raw_reporting)

        # Should we be reporting external messages?
        report: bool = False
        if isinstance(raw_reporting, bool):
            report = bool(raw_reporting)
        elif isinstance(raw_reporting, str):
            report = self.agent_url == raw_reporting
        elif isinstance(raw_reporting, List):
            report = self.agent_url in raw_reporting
        elif isinstance(raw_reporting, Dict):
            report = bool(raw_reporting.get(self.agent_url))

        if report:
            self.processor.add_processor(ExternalMessageProcessor(self.journal))

    def get_name(self) -> str:
        """
        :return: the name of the data-driven agent as it comes from the spec
        """
        return self.agent_url

    # pylint: disable=too-many-locals
    async def build(self) -> str:
        """
        Main entry point to the class.

        :return: A string representing a List of messages produced during this process.
        """
        message_list: List[Dict[str, Any]] = []

        arguments_dict: Dict[str, Any] = {
            "tool_start": True,
            "tool_args": self.arguments
        }
        message = AgentMessage(content="Received arguments:", structure=arguments_dict)
        await self.journal.write_message(message)

        # Create an AsyncAgentSession if necessary
        if self.session is None:
            invocation_context: InvocationContext = self.run_context.get_invocation_context()
            factory: AsyncAgentSessionFactory = invocation_context.get_async_session_factory()
            self.session = factory.create_session(self.agent_url, invocation_context)

        # Send off the input
        chat_request: Dict[str, Any] = self.gather_input(f"```json\n{json.dumps(self.arguments)}```",
                                                         self.sly_data)

        messages_str: str = ""
        try:
            # Note that we are not await-ing the response here because what is returned is a generator.
            # Proper await-ing for generator results is done in the "async for"-loop below.
            chat_responses: AsyncGenerator[Dict[str, Any], None] = self.session.streaming_chat(chat_request)
        except ValueError:
            # Could not reach the server for the external agent, so tell about it
            messages_str: str = f"Agent/tool {self.agent_url} was unreachable. " + \
                                "Cannot rely on results from it as a tool."
            full_name: str = Origination.get_full_name_from_origin(self.run_context.get_origin())
            logger: Logger = getLogger(full_name)
            logger.info(messages_str)
            return messages_str

        # The asynchronous generator will wait until the next response is available
        # from the stream.  When the other side is done, the iterator will exit the loop.
        empty = {}
        async for chat_response in chat_responses:

            response: Dict[str, Any] = chat_response.get("response", empty)
            await self.processor.async_process_message(response)

        # Get stuff back from the message processing
        answer: str = self.processor.get_compiled_answer()
        self.chat_context = self.processor.get_chat_context()
        returned_sly_data: Dict[str, Any] = self.processor.get_sly_data()

        # Redact any sly_data that came back based on "allow.from_downstream.sly_data"
        redactor = SlyDataRedactor(self.allow_from_downstream,
                                   config_keys=["sly_data"],
                                   allow_empty_dict=True)

        # Note: Instance of sly_data is no longer the shared instance.
        #       This ends up needing to be re-integrated in the RunContext.
        self.sly_data = redactor.filter_config(returned_sly_data)

        answer_dict: Dict[str, Any] = {
            "tool_end": True,
            "tool_output": answer
        }
        message = AgentMessage(content="Got result:", structure=answer_dict)
        await self.journal.write_message(message)

        # In terms of sending tool results back up the graph,
        # we really only care about immediately are the AI responses.
        # Eventually we will care about a fuller chat history.

        # Prepare the output
        message: Dict[str, Any] = {
            "role": "assistant",
            "content": answer
        }
        message_list.append(message)

        messages_str = json.dumps(message_list)
        return messages_str

    def gather_input(self, agent_input: str, sly_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send input to the external agent
        :param agent_input: A single string to send as input to the agent
        :param sly_data: Any private sly_data to accompany the input.
                    sly_data is intended not to be inserted into the chat stream.
        :return: The ChatRequest dictionary
        """
        # Set up a request
        chat_request = {
            "user_message": {
                "type": ChatMessageType.HUMAN,
                "text": agent_input
            }
        }

        if bool(self.chat_context):
            # Recall that non-empty dictionaries evaluate to True
            chat_request["chat_context"] = self.chat_context

        # At some point in the future we might want to block all
        # or parts of the sly_data from going to external agents.
        if sly_data is not None and len(sly_data.keys()) > 0:
            chat_request["sly_data"] = sly_data

        return chat_request

    async def delete_resources(self, parent_run_context: RunContext):
        """
        Cleans up after any allocated resources on their server side.
        :param parent_run_context: The RunContext which contains the scope
                    of operation of this CallableNode
        """
        await super().delete_resources(parent_run_context)
        self.session = None
