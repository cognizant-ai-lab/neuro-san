
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

import logging
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
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.info("AsyncioExecutorPool created: %s reuse: %s max concurrent: %d",
                         id(self), str(self.reuse_mode), self.max_concurrent)

    def get_executor(self) -> AsyncioExecutor:
        """
        Get active (running) executor from the pool
        :return: AsyncioExecutor instance
        """
        if self.reuse_mode:
            with self.lock:
                if len(self.pool) > 0:
                    result = self.pool.pop(0)
                    self.logger.info("Reusing AsyncExecutor %s", id(result))
                    return result
        # Create AsyncioExecutor outside of lock
        # to avoid potentially longer locked periods
        result = AsyncioExecutor()
        result.start()
        self.logger.info("Creating AsyncExecutor %s", id(result))
        return result

    def return_executor(self, executor: AsyncioExecutor):
        """
        Return AsyncioExecutor instance back to the pool of available instances.
        :param executor: AsyncioExecutor to return.
        """
        if self.reuse_mode:
            with self.lock:
                self.pool.append(executor)
                self.logger.info("Returned to pool: AsyncExecutor %s pool size: %d", id(executor), len(self.pool))
        else:
            # Shutdown AsyncioExecutor outside of lock
            # to avoid potentially longer locked periods
            self.logger.info("Shutting down: AsyncExecutor %s", id(executor))
            executor.shutdown()
