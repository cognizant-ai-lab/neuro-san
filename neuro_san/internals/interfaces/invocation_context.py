
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

from typing import Any
from typing import Dict

from threading import Event

from leaf_common.asyncio.asyncio_executor import AsyncioExecutor

from neuro_san.interfaces.reservationist import Reservationist
from neuro_san.internals.chat.async_collating_queue import AsyncCollatingQueue
from neuro_san.internals.interfaces.async_agent_session_factory import AsyncAgentSessionFactory
from neuro_san.internals.interfaces.context_type_toolbox_factory import ContextTypeToolboxFactory
from neuro_san.internals.interfaces.context_type_llm_factory import ContextTypeLlmFactory
from neuro_san.internals.interfaces.lingering_resource import LingeringResource
from neuro_san.internals.journals.journal import Journal
from neuro_san.internals.messages.origination import Origination


class InvocationContext(LingeringResource):
    """
    Top-level interface for encapsulating specific policy classes that pertain to
    a single invocation of an AgentSession or AsyncAgentSession, whether by way of a
    service call or library call.

    An InvocationContext will last for the duration of the work initiated by Session/request,
    which could outlive the Session/request itself, depending on just how its invocation is
    configured.
    """

    def start(self):
        """
        Starts the active components of this invocation context.
        Do this separately from constructor for more control.
        """
        raise NotImplementedError

    def get_effective_invocation(self) -> str:
        """
        :return: The effective invocation of the session
        """
        raise NotImplementedError

    def get_async_session_factory(self) -> AsyncAgentSessionFactory:
        """
        :return: The AsyncAgentSessionFactory associated with the invocation
        """
        raise NotImplementedError

    def get_asyncio_executor(self) -> AsyncioExecutor:
        """
        :return: The AsyncioExecutor associated with the invocation
        """
        raise NotImplementedError

    def get_origination(self) -> Origination:
        """
        :return: The Origination instance carrying state about tool instantation
                during the course of the AgentSession.
        """
        raise NotImplementedError

    def get_journal(self) -> Journal:
        """
        :return: The Journal instance that allows message reporting
                during the course of the AgentSession.
        """
        raise NotImplementedError

    def get_queue(self) -> AsyncCollatingQueue:
        """
        :return: The AsyncCollatingQueue instance via which messages are streamed to the
                AgentSession mechanics
        """
        raise NotImplementedError

    def get_metadata(self) -> Dict[str, str]:
        """
        :return: The metadata to pass along with any request
        """
        raise NotImplementedError

    async def close_of_request(self, parent_resource: LingeringResource = None):
        """
        Release resources owned by this context when the request is complete.
        This can happen earlier than when the work is complete.

        :param parent_resource: The parent resource, if any
        """
        raise NotImplementedError

    async def close_of_work(self, parent_resource: LingeringResource = None):
        """
        Release resources owned by this context when the work is all done.
        This can happen later than when the request is complete.

        :param parent_resource: The parent resource, if any
        """
        raise NotImplementedError

    def get_request_reporting(self) -> Dict[str, Any]:
        """
        :return: The request reporting dictionary
        """
        raise NotImplementedError

    def get_llm_factory(self) -> ContextTypeLlmFactory:
        """
        :return: The ContextTypeLlmFactory instance for the session
        """
        raise NotImplementedError

    def get_toolbox_factory(self) -> ContextTypeToolboxFactory:
        """
        :return: The ContextTypeToolboxFactory instance for the session
        """
        raise NotImplementedError

    def get_reservationist(self) -> Reservationist:
        """
        :return: The Reservationist instance for the session
        """
        raise NotImplementedError

    def get_port(self) -> int:
        """
        :return: The port on which the server was started
        """
        raise NotImplementedError

    def get_work_done_event(self) -> Event:
        """
        :return: The Event (synchronous) that will be set when work is done for this event
        """
        raise NotImplementedError

    def add_resource(self, resource: LingeringResource):
        """
        :param resource: The resource to add
        """
        raise NotImplementedError
