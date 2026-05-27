
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

from janus import Queue

from leaf_common.asyncio.asyncio_executor_pool import AsyncioExecutorPool

from neuro_san.internals.chat.async_collating_queue import AsyncCollatingQueue


class ServerContextLite:
    """
    Interface for getting a subset of information from the ServerContext.
    """

    def get_queues(self) -> Queue[AsyncCollatingQueue]:
        """
        :return: The janus Queue of queues for temporary agent deployment
        """
        raise NotImplementedError

    def get_server_port(self) -> int:
        """
        :return: The Server port
        """
        raise NotImplementedError

    def get_executor_pool(self) -> AsyncioExecutorPool:
        """
        :return: The AsyncioExecutorPool
        """
        raise NotImplementedError

    def get_event_work_queue(self) -> AsyncCollatingQueue:
        """
        :return: The event work queue
        """
        raise NotImplementedError
