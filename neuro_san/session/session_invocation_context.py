
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

from asyncio import Future

from leaf_common.asyncio.asyncio_executor import AsyncioExecutor
from leaf_server_common.logging.logging_setup import setup_extra_logging_fields

from neuro_san.internals.chat.async_collating_queue import AsyncCollatingQueue
from neuro_san.internals.interfaces.async_agent_session_factory import AsyncAgentSessionFactory
from neuro_san.internals.interfaces.context_type_toolbox_factory import ContextTypeToolboxFactory
from neuro_san.internals.interfaces.context_type_llm_factory import ContextTypeLlmFactory
from neuro_san.internals.interfaces.invocation_context import InvocationContext
from neuro_san.internals.journals.message_journal import MessageJournal
from neuro_san.internals.journals.journal import Journal
from neuro_san.internals.messages.origination import Origination


# pylint: disable=too-many-instance-attributes
class SessionInvocationContext(InvocationContext):
    """
    Implementation of InvocationContext which encapsulates specific policy classes that pertain to
    a single invocation of an AgentSession, whether by way of a
    service call or library call.
    """

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def __init__(self, async_session_factory: AsyncAgentSessionFactory,
                 llm_factory: ContextTypeLlmFactory,
                 toolbox_factory: ContextTypeToolboxFactory = None,
                 metadata: Dict[str, str] = None,
                 originates_from_async: bool = False):
        """
        Constructor

        :param async_session_factory: The AsyncAgentSessionFactory to use
                        when connecting with external agents.
        :param llm_factory: The ContextTypeLlmFactory instance
        :param metadata: A grpc metadata of key/value pairs to be inserted into
                         the header. Default is None. Preferred format is a
                         dictionary of string keys to string values.
        :param origininates_from_async: Optional boolean that tells us if we are
                        being used from within an async environment already.
                        This effects close() behavior.
        """

        self.async_session_factory: AsyncAgentSessionFactory = async_session_factory
        # Get an async executor to run all tasks for this session instance:
        self.asyncio_executor: AsyncioExecutor = AsyncioExecutor()
        self.origination: Origination = Origination()
        self.queue: AsyncCollatingQueue = AsyncCollatingQueue()
        self.journal: Journal = MessageJournal(self.queue)
        self.metadata: Dict[str, str] = metadata
        self.request_reporting: Dict[str, Any] = {}
        self.llm_factory: ContextTypeLlmFactory = llm_factory
        self.toolbox_factory: ContextTypeToolboxFactory = toolbox_factory
        self.originates_from_async: bool = originates_from_async

    def start(self):
        """
        Starts the active components of this invocation context.
        Do this separately from constructor for more control.
        Currently, we only start internal AsyncioExecutor.
        """
        self.asyncio_executor.start()

        # Set up logging fields within the thread, so we have consistent logging from async calls.
        # Ignore the future that is returned - we trust it will get done.
        _: Future = self.asyncio_executor.submit(
            "logging_setup", setup_extra_logging_fields,
            metadata_dict=self.metadata)

    def get_async_session_factory(self) -> AsyncAgentSessionFactory:
        """
        :return: The AsyncAgentSessionFactory associated with the invocation
        """
        return self.async_session_factory

    def get_asyncio_executor(self) -> AsyncioExecutor:
        """
        :return: The AsyncioExecutor associated with the invocation
        """
        return self.asyncio_executor

    def get_origination(self) -> Origination:
        """
        :return: The Origination instance carrying state about tool instantation
                during the course of the AgentSession.
        """
        return self.origination

    def get_journal(self) -> Journal:
        """
        :return: The Journal instance that allows message reporting
                during the course of the AgentSession.
        """
        return self.journal

    def get_queue(self) -> AsyncCollatingQueue:
        """
        :return: The AsyncCollatingQueue instance via which messages are streamed to the
                AgentSession mechanics
        """
        return self.queue

    def get_metadata(self) -> Dict[str, str]:
        """
        :return: The metadata to pass along with any request
        """
        return self.metadata

    def close(self):
        """
        Release resources owned by this context
        """
        if self.asyncio_executor is not None:
            if not self.originates_from_async:
                self.asyncio_executor.shutdown()
            self.asyncio_executor = None
        if self.queue is not None:
            self.queue.close()

    def get_request_reporting(self) -> Dict[str, Any]:
        """
        :return: The request reporting dictionary
        """
        return self.request_reporting

    def get_llm_factory(self) -> ContextTypeLlmFactory:
        """
        :return: The ContextTypeLlmFactory instance for the session
        """
        return self.llm_factory

    def get_toolbox_factory(self) -> ContextTypeToolboxFactory:
        """
        :return: The ContextTypeToolboxFactory instance for the session
        """
        return self.toolbox_factory

    def reset(self):
        """
        Resets the instance for a subsequent use for another exchange with the agent network.
        """
        # Origination needs to be reset so that origin information can match up
        # with what is in the chat_context. If we do not reset this, then library calls
        # to DirectAgentSession do not properly carry forward any memory of the conversation
        # in subsequent interactions with the same network.
        self.origination.reset()
