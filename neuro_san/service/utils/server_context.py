
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
from typing import Optional

from threading import Lock
from os import environ

from janus import Queue

from leaf_common.asyncio.asyncio_executor_pool import AsyncioExecutorPool

from neuro_san.interfaces.agent_session_constants import AgentSessionConstants
from neuro_san.internals.chat.async_collating_queue import AsyncCollatingQueue
from neuro_san.internals.interfaces.storage_class import StorageClass
from neuro_san.internals.network_providers.agent_network_storage import AgentNetworkStorage
from neuro_san.internals.network_providers.expiring_agent_network_storage \
    import ExpiringAgentNetworkStorage
from neuro_san.service.interfaces.agent_authorizer import AgentAuthorizer
from neuro_san.service.interfaces.server_context_lite import ServerContextLite
from neuro_san.service.utils.server_status import ServerStatus
from neuro_san.service.utils.mcp_server_context import McpServerContext


# pylint: disable=too-many-instance-attributes
class ServerContext(ServerContextLite):
    """
    Class that contains global-ish state for each instance of a server.
    """

    def __init__(self):
        """
        Constructor.
        """
        self.server_status: ServerStatus = None
        # NB: do NOT construct the AsyncioExecutorPool here. When Tornado is
        # configured for multiple worker processes (AGENT_HTTP_SERVER_INSTANCES
        # > 1), the server forks *after* this instance is created but before
        # any request-path code runs. AsyncioExecutorPool starts a daemon GC
        # thread in its constructor, and threads do not survive fork -- the
        # child ends up with a _gc_thread reference to a thread that no longer
        # exists, and stale executors are never reaped in the workers.
        # Lazy-construct in get_executor_pool() so each worker builds its own.
        self.executor_pool: Optional[AsyncioExecutorPool] = None
        self._executor_pool_lock: Lock = Lock()
        self.queues: Queue[AsyncCollatingQueue] = None
        self.mcp_server_context: McpServerContext = McpServerContext()
        self.server_port: int = AgentSessionConstants.DEFAULT_HTTP_PORT
        self.event_work_queue: AsyncCollatingQueue = None

        # Number of worker processes for the server. To be set by the server initialization code.
        self.num_workers: int = 0
        # Id of the current worker process. To be set by the server initialization code.
        self.worker_id: int = 0

        # Dictionary is string key (describing scope) to AgentNetworkStorage grouping.
        self.network_storage_dict: Dict[str, AgentNetworkStorage] = {}
        for storage_class in StorageClass.ALL_PERMANENT:
            self.network_storage_dict[storage_class] = AgentNetworkStorage()
        self.network_storage_dict[StorageClass.TEMP] = ExpiringAgentNetworkStorage()

        self.periodic_configs: Dict[str, Dict[str, Any]] = {}
        self.agent_authorizer: AgentAuthorizer = None

    def start(self):
        """
        Create and start any process fork-sensitive resources
        needed by this server context.
        """
        self.queues = Queue()
        self.event_work_queue = AsyncCollatingQueue()

    def set_temp_storage_max_items(self, max_items: int):
        """
        Configure the maximum number of temporary networks to keep in memory.
        When exceeded, least recently used items are evicted.
        :param max_items: Maximum number of items. 0 or negative means unlimited.
        """
        temp_storage: ExpiringAgentNetworkStorage = self.network_storage_dict.get(StorageClass.TEMP)
        if temp_storage is not None:
            temp_storage.set_max_agent_networks(max_items)

    def get_executor_pool(self) -> AsyncioExecutorPool:
        """
        :return: The AsyncioExecutorPool for the current worker process.
                 Constructed on first access so that each post-fork worker
                 gets its own pool (with its own live GC thread), rather
                 than inheriting a dead reference from the parent.
        """
        if self.executor_pool is None:
            # Default of None reverts to ThreadPoolExecutor default of (num_cpus + 4).
            max_workers: int = None
            max_workers_str: str = environ.get("AGENT_MAX_WORKERS_PER_REQUEST", None)
            if max_workers_str is not None:
                try:
                    max_workers = int(max_workers_str)
                    if max_workers <= 0:
                        # Revert to default
                        max_workers = None
                except ValueError:
                    pass

            with self._executor_pool_lock:
                if self.executor_pool is None:
                    self.executor_pool = AsyncioExecutorPool(reuse_mode=True,
                                                             idle_timeout_seconds=30,
                                                             max_workers=max_workers)
        return self.executor_pool

    def set_worker_info(self, worker_id: int, num_workers: int):
        """
        Sets the worker id and total number of workers for this server instance.
        :param worker_id: The id of the current worker process (0-based).
        :param num_workers: The total number of worker processes for the server.
        """
        self.worker_id = worker_id
        self.num_workers = num_workers

    def get_worker_id(self) -> int:
        """
        :return: The id of the current worker process (0-based).
        """
        return self.worker_id

    def get_num_workers(self) -> int:
        """
        :return: The total number of worker processes for the server.
        """
        return self.num_workers

    def dump_tasks_in_used_executors(self, per_loop_timeout_s: float = 2.0) -> Dict[str, Any]:
        """
        Debug helper: snapshot the asyncio tasks currently living on every
        AsyncioExecutor in the pool's "used" list. For each executor, this
        schedules a one-shot coroutine on that executor's event loop that
        enumerates asyncio.all_tasks() and captures each task's name, coro
        qualname, done/cancelled state, and suspended stack. Results are
        collected across loops via run_coroutine_threadsafe.

        If a loop is unresponsive within per_loop_timeout_s -- for example,
        because it is CPU-bound on a synchronous hog and cannot service any
        new callback -- that executor's entry is marked as "unresponsive"
        rather than blocking indefinitely. An unresponsive loop is itself a
        strong diagnostic signal ("this loop cannot even run our probe").

        Intended for on-demand invocation from a debug endpoint or a signal
        handler while the server is wedged. Do NOT call from performance-
        sensitive paths: it walks every task frame on every used executor.

        :param per_loop_timeout_s: How long to wait for a single loop's
                    probe coroutine to run. Loops that don't respond by
                    then are recorded as unresponsive.
        :return: A dict keyed by str(id(executor)) with per-executor entries
                 describing loop status and (when responsive) the list of
                 tasks with their suspended stacks. See format_task_dump()
                 for a printable rendering.
        """
        result: Dict[str, Any] = {}
        if self.executor_pool is None:
            # Nothing has ever asked for an executor in this worker.
            return result

        result = self.executor_pool.dump_tasks_in_used_executors(per_loop_timeout_s=per_loop_timeout_s)
        return result

    @staticmethod
    def format_task_dump(dump: Dict[str, Any]) -> str:
        """
        Render the output of dump_tasks_in_used_executors() as a printable
        multi-line string. Useful for logging or writing into a debug HTTP
        response.

        :param dump: A dict returned by dump_tasks_in_used_executors().
        :return: A human-readable multi-line string.
        """
        if not dump:
            return "(no used executors)"
        return AsyncioExecutorPool.format_task_dump(dump)

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

    def get_event_work_queue(self) -> AsyncCollatingQueue:
        """
        :return: The event work queue
        """
        return self.event_work_queue

    def set_periodic_configs(self, periodic_configs: Dict[str, Dict[str, Any]]):
        """
        Sets the periodic configs
        """
        self.periodic_configs = periodic_configs

    def get_periodic_configs(self) -> Dict[str, Dict[str, Any]]:
        """
        :return: the periodic configs
        """
        return self.periodic_configs

    def set_agent_authorizer(self, agent_authorizer: AgentAuthorizer):
        """
        Sets the agent authorizer instance
        """
        self.agent_authorizer = agent_authorizer

    def get_agent_authorizer(self) -> AgentAuthorizer:
        """
        :return: the agent authorizer instance
        """
        return self.agent_authorizer
