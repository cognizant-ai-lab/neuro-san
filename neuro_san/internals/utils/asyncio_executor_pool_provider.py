
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
"""
See class comments
"""
from leaf_common.asyncio.asyncio_executor_pool import AsyncioExecutorPool


class AsyncioExecutorPoolProvider:
    """
    Class providing server-wide instance of AsyncioExecutorPool
    for use by specific agent services.
    """

    _executors_pool: AsyncioExecutorPool = None

    @classmethod
    def set_executors_pool(cls, reuse_mode: bool = True):
        cls._executors_pool = AsyncioExecutorPool(reuse_mode=reuse_mode)

    @classmethod
    def get_executors_pool(cls):
        return cls._executors_pool
