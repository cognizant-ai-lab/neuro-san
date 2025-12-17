
# Copyright © 2023-2025 Cognizant Technology Solutions Corp, www.cognizant.com.
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
from __future__ import annotations

from typing import Any
from typing import Callable
from typing import Dict

from copy import copy
import functools

from leaf_common.asyncio.asyncio_executor import AsyncioExecutor
from leaf_common.asyncio.asyncio_executor_pool import AsyncioExecutorPool
from leaf_server_common.logging.logging_setup import setup_extra_logging_fields

from neuro_san.interfaces.reservationist import Reservationist
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

    # pylint: disable=too-many-arguments
    # pylint: disable=too-many-positional-arguments
    def __init__(self, agent_name: str,
                 async_session_factory: AsyncAgentSessionFactory,
                 async_executors_pool: AsyncioExecutorPool,
                 llm_factory: ContextTypeLlmFactory,
                 toolbox_factory: ContextTypeToolboxFactory = None,
                 metadata: Dict[str, str] = None,
                 reservationist: Reservationist = None,
                 port: int = None):
        """
        Constructor

        :param agent_name: The name of the agent
        :param async_session_factory: The AsyncAgentSessionFactory to use
                        when connecting with external agents.
        :param async_executors_pool: pool of AsyncioExecutors to use for obtaining
                         an executor instance to use for this context;
        :param llm_factory: The ContextTypeLlmFactory instance
        :param toolbox_factory: The ContextTypeToolboxFactory instance
        :param metadata: A request metadata of key/value pairs to be inserted into
                         the header. Default is None. Preferred format is a
                         dictionary of string keys to string values.
        :param reservationist: The Reservationist instance to use.
        :param port: The port on which the server was started
        """

        # From args
        self.agent_name: str = agent_name
        self.async_session_factory: AsyncAgentSessionFactory = async_session_factory
        self.async_executors_pool: AsyncioExecutorPool = async_executors_pool
        self.llm_factory: ContextTypeLlmFactory = llm_factory
        self.toolbox_factory: ContextTypeToolboxFactory = toolbox_factory
        self.metadata: Dict[str, str] = metadata
        self.reservationist: Reservationist = reservationist
        self.port: int = port

        # Internal
        # Get an async executor to run all tasks for this session instance:
        self.asyncio_executor: AsyncioExecutor = self.async_executors_pool.get_executor()
        self.request_reporting: Dict[str, Any] = {}
        self.origination: Origination = Origination()

        # Anything that has to do with the queue will need a new instance in
        # safe_shallow_copy() below to keep AsyncDirectAgentSessions happy.
        self.queue: AsyncCollatingQueue = AsyncCollatingQueue()
        self.journal: Journal = MessageJournal(self.queue)

    def start(self):
        """
        Starts the active components of this invocation context.
        Do this separately from constructor for more control.
        Currently, we only start internal AsyncioExecutor.
        It could be already running, but starting it twice is allowed.
        """
        # Wrap it up into a single function with no parameters
        # for easier handling downstream.
        logging_setup: Callable = functools.partial(setup_extra_logging_fields, metadata_dict=self.metadata)
        self.asyncio_executor.start()
        # Run logging setup as event-loop initialization step -
        # make sure it is finished before we start to use this AsyncioExecutor instance.
        self.asyncio_executor.initialize(logging_setup)

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
            self.async_executors_pool.return_executor(self.asyncio_executor)
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

    def get_reservationist(self) -> Reservationist:
        """
        :return: The Reservationist instance for the session
        """
        return self.reservationist

    def get_agent_name(self) -> str:
        """
        :return: The agent name for the session
        """
        return self.agent_name

    def get_port(self) -> int:
        """
        :return: The port on which the server was started
        """
        return self.port

    def reset(self):
        """
        Resets the instance for a subsequent use for another exchange with the agent network.
        """
        # Origination needs to be reset so that origin information can match up
        # with what is in the chat_context. If we do not reset this, then library calls
        # to DirectAgentSession do not properly carry forward any memory of the conversation
        # in subsequent interactions with the same network.
        self.origination.reset()

    def safe_shallow_copy(self) -> SessionInvocationContext:
        """
        Makes a safe shallow copy of the invocation context.
        Generally used with direct sessions.
        """

        invocation_context: SessionInvocationContext = copy(self)

        # We need a different queue in order to call external agents with direct sessions.
        invocation_context.queue: AsyncCollatingQueue = AsyncCollatingQueue()

        # Now that the queue has changed, we need a new Journal as well
        # to be sure that the messages are sent to the correct queue.
        invocation_context.journal: Journal = MessageJournal(invocation_context.queue)

        return invocation_context
