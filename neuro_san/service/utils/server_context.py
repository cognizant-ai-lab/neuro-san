
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
from typing import List
from typing import Optional

import asyncio
import concurrent.futures
from threading import Lock

from janus import Queue

from leaf_common.asyncio.asyncio_executor import AsyncioExecutor
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
        self.queues: Queue[AsyncCollatingQueue] = Queue()
        self.mcp_server_context: McpServerContext = McpServerContext()
        self.server_port: int = AgentSessionConstants.DEFAULT_HTTP_PORT
        self.event_work_queue: AsyncCollatingQueue = AsyncCollatingQueue()

        # Dictionary is string key (describing scope) to AgentNetworkStorage grouping.
        self.network_storage_dict: Dict[str, AgentNetworkStorage] = {}
        for storage_class in StorageClass.ALL_PERMANENT:
            self.network_storage_dict[storage_class] = AgentNetworkStorage()
        self.network_storage_dict[StorageClass.TEMP] = ExpiringAgentNetworkStorage()

        self.periodic_configs: Dict[str, Dict[str, Any]] = {}
        self.agent_authorizer: AgentAuthorizer = None

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
            with self._executor_pool_lock:
                if self.executor_pool is None:
                    self.executor_pool = AsyncioExecutorPool(reuse_mode=True,
                                                             idle_timeout_seconds=30)
        return self.executor_pool

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

        # Snapshot the "used" list under the pool's lock so we don't race
        # with get_executor()/return_executor() while iterating.
        with self.executor_pool.lock:
            used_snapshot: List[AsyncioExecutor] = list(self.executor_pool.pool_used)

        for executor in used_snapshot:
            executor_key: str = str(id(executor))
            loop: asyncio.AbstractEventLoop = executor.get_event_loop()
            if loop is None or not loop.is_running():
                result[executor_key] = {"loop_state": "not_running", "tasks": []}
                continue

            future: concurrent.futures.Future = asyncio.run_coroutine_threadsafe(
                self._collect_tasks_on_current_loop(), loop)
            try:
                tasks = future.result(timeout=per_loop_timeout_s)
                result[executor_key] = {"loop_state": "responded", "tasks": tasks}
            except concurrent.futures.TimeoutError:
                future.cancel()
                result[executor_key] = {"loop_state": "unresponsive_timeout", "tasks": []}
            except Exception as exc:  # pylint: disable=broad-exception-caught
                result[executor_key] = {
                    "loop_state": "probe_error",
                    "error": f"{type(exc).__name__}: {exc}",
                    "tasks": [],
                }
        return result

    @staticmethod
    async def _collect_tasks_on_current_loop() -> List[Dict[str, Any]]:
        """
        Probe coroutine scheduled onto each target loop. Runs inside that
        loop's context so asyncio.all_tasks() sees every task on it; the
        probe filters itself out of the result.
        """
        me: asyncio.Task = asyncio.current_task()
        tasks_info: List[Dict[str, Any]] = []
        for task in asyncio.all_tasks():
            if task is me:
                continue
            coro = task.get_coro()
            stack_frames: List[Dict[str, Any]] = []
            for frame in task.get_stack():
                stack_frames.append({
                    "file": frame.f_code.co_filename,
                    "line": frame.f_lineno,
                    "func": frame.f_code.co_name,
                })
            tasks_info.append({
                "name": task.get_name(),
                "coro": getattr(coro, "__qualname__", repr(coro)),
                "done": task.done(),
                "cancelled": task.cancelled(),
                "stack": stack_frames,
            })
        return tasks_info

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
        lines: List[str] = []
        for executor_key, entry in dump.items():
            loop_state: str = entry.get("loop_state", "unknown")
            tasks: List[Dict[str, Any]] = entry.get("tasks", [])
            lines.append(f"== executor {executor_key}  loop_state={loop_state}  "
                         f"tasks={len(tasks)} ==")
            if loop_state == "probe_error":
                lines.append(f"   probe_error: {entry.get('error')}")
            for task in tasks:
                lines.append(f"  - name={task['name']!r}  coro={task['coro']}  "
                             f"done={task['done']}  cancelled={task['cancelled']}")
                for frame in task.get("stack", []):
                    lines.append(f"      File \"{frame['file']}\", "
                                 f"line {frame['line']}, in {frame['func']}")
        return "\n".join(lines)

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
