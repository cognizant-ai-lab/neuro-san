
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

from typing import Dict

from janus import Queue

from leaf_common.asyncio.asyncio_executor_pool import AsyncioExecutorPool

from neuro_san.interfaces.agent_session_constants import AgentSessionConstants
from neuro_san.internals.chat.async_collating_queue import AsyncCollatingQueue
from neuro_san.internals.network_providers.agent_network_storage import AgentNetworkStorage
from neuro_san.internals.network_providers.expiring_agent_network_storage \
    import ExpiringAgentNetworkStorage
from neuro_san.service.utils.server_status import ServerStatus
from neuro_san.service.utils.mcp_server_context import McpServerContext


class ServerContext:
    """
    Class that contains global-ish state for each instance of a server.
    """

    def __init__(self):
        """
        Constructor.
        """
        self.server_status: ServerStatus = None
        self.executor_pool = AsyncioExecutorPool(reuse_mode=True)
        self.queues: Queue[AsyncCollatingQueue] = Queue()
        self.mcp_server_context: McpServerContext = McpServerContext()
        self.server_port: int = AgentSessionConstants.DEFAULT_HTTP_PORT

        # Dictionary is string key (describing scope) to AgentNetworkStorage grouping.
        self.network_storage_dict: Dict[str, AgentNetworkStorage] = {
            "protected": AgentNetworkStorage(),
            "public": AgentNetworkStorage(),
            "temp": ExpiringAgentNetworkStorage()
        }

    def get_executor_pool(self) -> AsyncioExecutorPool:
        """
        :return: The AsyncioExecutorPool
        """
        return self.executor_pool

    def set_server_status(self, server_status: ServerStatus):
        """
        Sets the server status
        """
        self.server_status = server_status

    def get_server_status(self) -> ServerStatus:
        """
        :return: The ServerStatus
        """
        return self.server_status

    def get_network_storage_dict(self) -> Dict[str, AgentNetworkStorage]:
        """
        :return: The Network Storage dictionary
        """
        return self.network_storage_dict

    def get_queues(self) -> Queue[AsyncCollatingQueue]:
        """
        :return: The janus Queue of queues for temporary agent deployment
        """
        return self.queues

    def no_queues(self):
        """
        Resets the queues to None as a signal to other parts of code base
        that we don't need Reservationists
        """
        self.queues = None

    def get_mcp_server_context(self) -> McpServerContext:
        """
        :return: The MCPServerContext for MCP service operations
        """
        return self.mcp_server_context

    def set_server_port(self, port: int):
        """
        Sets the server port
        """
        self.server_port = port

    def get_server_port(self) -> int:
        """
        :return: The Server port
        """
        return self.server_port
