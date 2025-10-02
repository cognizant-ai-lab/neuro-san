
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

from leaf_common.asyncio.asyncio_executor import AsyncioExecutor

from neuro_san.interfaces.reservationist import Reservationist
from neuro_san.internals.chat.async_collating_queue import AsyncCollatingQueue
from neuro_san.internals.interfaces.async_agent_session_factory import AsyncAgentSessionFactory
from neuro_san.internals.interfaces.context_type_toolbox_factory import ContextTypeToolboxFactory
from neuro_san.internals.interfaces.context_type_llm_factory import ContextTypeLlmFactory
from neuro_san.internals.journals.journal import Journal
from neuro_san.internals.messages.origination import Origination


class InvocationContext:
    """
    Interface for encapsulating specific policy classes that pertain to
    a single invocation of an AgentSession or AsyncAgentSession, whether by way of a
    service call or library call.
    """

    def start(self):
        """
        Starts the active components of this invocation context.
        Do this separately from constructor for more control.
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

    def close(self):
        """
        Release resources owned by this context
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
