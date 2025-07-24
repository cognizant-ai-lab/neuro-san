
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

import threading
from leaf_common.asyncio.asyncio_executor import AsyncioExecutor

class AsyncioExecutorPool:
    """
    Class maintaining a dynamic set of reusable AsyncioExecutor instances.
    """

    def __init__(self, max_concurrent: int, reuse_mode: bool = True):
        """
        Constructor.
        :param max_concurrent: maximum allowed number of concurrently running AsyncioExecutors.
        :param reuse_mode: True, if requested executor instances
                                 are taken from pool of available ones (pool mode);
                           False, if requested executor instances are created new
                                 and shutdown on return (backward compatible mode)
        """
        self.max_concurrent = max_concurrent
        self.reuse_mode: bool = reuse_mode
        self.pool = []
        self.lock: threading.Lock = threading.Lock()

    def get_executor(self) -> AsyncioExecutor:
        """
        Get active (running) executor from the pool
        :return: AsyncioExecutor instance
        """
        with self.lock:
            result: AsyncioExecutor = None
            if self.reuse_mode and len(self.pool) > 0:
                result = self.pool.pop(0)
            else:
                result = AsyncioExecutor()
                result.start()
            return result

    def return_executor(self, executor: AsyncioExecutor):
        """
        Return AsyncioExecutor instance back to the pool of available instances.
        :param executor: AsyncioExecutor to return.
        """
        if self.reuse_mode:
            with self.lock:
                self.pool.append(executor)
        else:
            executor.shutdown()
