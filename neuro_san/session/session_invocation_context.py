
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
from __future__ import annotations

from typing import Any
from typing import Awaitable
from typing import Callable
from typing import Dict
from typing import List

from asyncio import AbstractEventLoop
from asyncio import get_running_loop
from asyncio import run_coroutine_threadsafe
from copy import copy
from concurrent.futures import Future
from functools import partial
from threading import Event

from leaf_common.asyncio.asyncio_executor import AsyncioExecutor
from leaf_common.asyncio.asyncio_executor_pool import AsyncioExecutorPool
from leaf_server_common.logging.logging_setup import setup_extra_logging_fields

from neuro_san.interfaces.reservationist import Reservationist
from neuro_san.internals.chat.async_collating_queue import AsyncCollatingQueue
from neuro_san.internals.interfaces.async_agent_session_factory import AsyncAgentSessionFactory
from neuro_san.internals.interfaces.context_type_toolbox_factory import ContextTypeToolboxFactory
from neuro_san.internals.interfaces.context_type_llm_factory import ContextTypeLlmFactory
from neuro_san.internals.interfaces.invocation_context import InvocationContext
from neuro_san.internals.interfaces.lingering_resource import LingeringResource
from neuro_san.internals.journals.message_journal import MessageJournal
from neuro_san.internals.journals.journal import Journal
from neuro_san.internals.messages.origination import Origination


# pylint: disable=too-many-instance-attributes,too-many-public-methods
class SessionInvocationContext(InvocationContext):
    """
    Implementation of InvocationContext which encapsulates specific policy classes that pertain to
    a single invocation of an AgentSession, whether by way of a service call or library call.

    A SessionInvocationContext will last for the duration of the work initiated by Session/request,
    which could outlive the Session/request itself, depending on just how its invocation is
    configured.
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
                 port: int = None,
                 effective_invocation: str = "chatbot",
                 event_work_queue: AsyncCollatingQueue = None):
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
        :param effective_invocation: A string representing the effective invocation of the session.
        :param event_work_queue: The AsyncCollatingQueue instance to use to queue up work
                            for events that will be finished up after the request ends.
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
        self.effective_invocation: str = effective_invocation
        self.event_work_queue: AsyncCollatingQueue = event_work_queue

        # Internal
        # Get an async executor to run all tasks for this session instance:
        self.asyncio_executor: AsyncioExecutor = self.async_executors_pool.get_executor()
        self.request_reporting: Dict[str, Any] = {}
        self.origination: Origination = Origination()

        # Anything that has to do with the queue will need a new instance in
        # safe_shallow_copy() below to keep AsyncDirectAgentSessions happy.
        self.queue: AsyncCollatingQueue = AsyncCollatingQueue()
        self.journal: Journal = MessageJournal(self.queue)
        self.resources: List[LingeringResource] = []
        self.work_done_event: Event = Event()
        self.request_finished: bool = False
        self.is_cloned: bool = False

    def start(self):
        """
        Starts the active components of this invocation context.
        Do this separately from constructor for more control.
        Currently, we only start internal AsyncioExecutor.
        It could be already running, but starting it twice is allowed.
        """
        # Wrap it up into a single function with no parameters
        # for easier handling downstream.
        logging_setup: Callable = partial(setup_extra_logging_fields, metadata_dict=self.metadata)
        self.asyncio_executor.start()
        # Run logging setup as event-loop initialization step -
        # make sure it is finished before we start to use this AsyncioExecutor instance.
        self.asyncio_executor.initialize(logging_setup)

    def get_effective_invocation(self) -> str:
        """
        :return: The effective invocation of the session
        """
        return self.effective_invocation

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

    def add_resource(self, resource: LingeringResource):
        """
        :param resource: The resource to add
        """
        self.resources.append(resource)

    async def close_of_request(self, parent_resource: LingeringResource = None):
        """
        Release resources owned by this context when the request is complete.
        This can happen earlier than when the work is complete.

        :param parent_resource: The parent resource, if any
        """
        if self.queue is not None:
            self.queue.close()
            self.queue = None

        for resource in self.resources:
            await resource.close_of_request()

    async def close_of_work(self, parent_resource: LingeringResource = None):
        """
        Release resources owned by this context when the work is all done.
        This can happen later than when the request is complete.

        Note: Any time close_of_work() is called, return_executor() should also be called
              but not in the executor.  Use the synchronous done_with_work() for that combo.

        :param parent_resource: The parent resource, if any
        """
        # Close resources first cuz they might need the executor
        for resource in self.resources:
            await resource.close_of_work()

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

        if self.queue is not None:
            self.queue.reset()
        else:
            # When creating a new queue, we need to make sure that the journal knows about it
            self.queue = AsyncCollatingQueue()
            self.journal: Journal = MessageJournal(self.queue)

        # Be sure we have an executor
        if self.asyncio_executor is None:
            self.asyncio_executor = self.async_executors_pool.get_executor()

    def safe_shallow_copy(self, invocation: str = None) -> SessionInvocationContext:
        """
        Makes a safe shallow copy of the invocation context.
        Generally used with direct sessions.

        :param invocation: String describing how the agent wants to be invoked.
                            Can be: "chatbot" - implies waiting for an answer.
                                    "event" - implies no answer needed
                                    None - implies chatbot
        :return: A copy of the invocation context
        """

        invocation_context: SessionInvocationContext = copy(self)

        # Mark the invocation context as cloned
        # This tells us that it is not the original/root and will prevent
        # mis-happenings like returning the executor to the pool too early.
        invocation_context.is_cloned = True

        # We need a different Event to signal work is done
        # Work being all done on a sub-invocation is not the same as work all done on the root.
        invocation_context.work_done_event: Event = Event()

        # We need different resources to close
        # Resources are not shared between sub-invocations
        invocation_context.resources: List[LingeringResource] = []

        # We need a different queue in order to call external agents with direct sessions.
        invocation_context.queue: AsyncCollatingQueue = AsyncCollatingQueue()

        # Now that the queue has changed, we need a new Journal as well
        # to be sure that the messages are sent to the correct queue.
        invocation_context.journal: Journal = MessageJournal(invocation_context.queue)

        # If an invocation was provided, use it
        if invocation is not None:
            invocation_context.effective_invocation = invocation

        return invocation_context

    def get_work_done_event(self) -> Event:
        """
        :return: The Event (synchronous) that will be set when work is done for this event
        """
        return self.work_done_event

    def finish_request(self):
        """
        Clean up our resources.
        Depending on the invocation, we might Queue ourselves to let our work finish on its own
        so that some of the resources can be cleaned up later.
        """
        # Only ever do this once
        if self.request_finished:
            return
        self.request_finished = True

        close_of_work_now: bool = True
        try:
            self._run_in_executor_until_complete("finish_request", self.close_of_request())

            if self.get_effective_invocation() == "event":
                # Finish the event work later only if there is something that will finish it for us.
                if self.event_work_queue is not None:
                    close_of_work_now = False
                    # Need to do synchronous put because we are in a different event loop.
                    self._run_in_executor_until_complete("finish_request",
                                                         self.event_work_queue.put(self, synchronous=True))
        finally:
            if close_of_work_now:
                # Still need to close resources, per above determination
                self.done_with_work("finish_request")

    def _run_in_executor_until_complete(self, submitter_id: str, coroutine: Awaitable) -> Future:
        """
        Submits a function to be run on the executor and runs until complete.
        Note this is synchronous and can be run from within the executor or another event loop.
        """
        # We need to know if we are running in the same event loop as the executor
        other_loop: AbstractEventLoop = self.asyncio_executor.get_event_loop()
        loop: AbstractEventLoop = None
        try:
            loop = get_running_loop()
        except RuntimeError:
            pass

        future: Future = None
        if loop == other_loop:
            # If we are running in the same event loop as the executor, just run it directly
            # If we try to wait for the result here it will never return.
            future = self.asyncio_executor.create_task(coroutine, submitter_id, raise_exception=True)
        else:
            # Use some magic to run in a different event loop
            future = run_coroutine_threadsafe(coroutine, other_loop)
            # Wait for the result...
            result: Any = future.result()
            # ... that we don't really care about.
            _ = result
            future = None

        return future

    def done_with_work(self, submitter_id: str = None):
        """
        Runs close_of_work() on the executor and potentially returns the executor back to the pool
        """
        self._run_in_executor_until_complete(submitter_id, self.close_of_work())

        if self.is_cloned:
            # Clones via safe_shallow_copy() share the same AsyncioExecutor,
            # so don't return it back to the pool just yet. Let the mama do that.
            return

        if self.asyncio_executor is not None:
            self.async_executors_pool.return_executor(self.asyncio_executor)
            self.asyncio_executor = None
