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
import asyncio

from typing import AsyncIterator
from typing import List

from leaf_common.asyncio.asyncio_executor import AsyncioExecutor

from neuro_san.internals.utils.asyncio_util import AsyncioUtil


class AsyncioUtilCallStacks:
    """
    Test helper that builds synchronous and asynchronous call stacks of varying depth,
    each ending in a call to AsyncioUtil.is_running_in_executor().
    """

    # Synchronous call stacks

    @staticmethod
    def sync_level_1(executor: AsyncioExecutor) -> bool:
        """
        Calls is_running_in_executor() directly from a synchronous method.

        :param executor: The AsyncioExecutor passed to is_running_in_executor()
        :return: The result of is_running_in_executor()
        """
        return AsyncioUtil.is_running_in_executor(executor)

    @staticmethod
    def sync_level_2(executor: AsyncioExecutor) -> bool:
        """
        Calls is_running_in_executor() through one intermediate synchronous method.

        :param executor: The AsyncioExecutor passed to is_running_in_executor()
        :return: The result of is_running_in_executor()
        """
        return AsyncioUtilCallStacks.sync_level_1(executor)

    @staticmethod
    def sync_level_3(executor: AsyncioExecutor) -> bool:
        """
        Calls is_running_in_executor() through two intermediate synchronous methods.

        :param executor: The AsyncioExecutor passed to is_running_in_executor()
        :return: The result of is_running_in_executor()
        """
        return AsyncioUtilCallStacks.sync_level_2(executor)

    # Asynchronous call stacks

    @staticmethod
    async def async_level_1(executor: AsyncioExecutor) -> bool:
        """
        Calls is_running_in_executor() directly from an async method.

        :param executor: The AsyncioExecutor passed to is_running_in_executor()
        :return: The result of is_running_in_executor()
        """
        return AsyncioUtil.is_running_in_executor(executor)

    @staticmethod
    async def async_level_2(executor: AsyncioExecutor) -> bool:
        """
        Calls is_running_in_executor() through one intermediate async method.

        :param executor: The AsyncioExecutor passed to is_running_in_executor()
        :return: The result of is_running_in_executor()
        """
        return await AsyncioUtilCallStacks.async_level_1(executor)

    @staticmethod
    async def async_level_3(executor: AsyncioExecutor) -> bool:
        """
        Calls is_running_in_executor() through two intermediate async methods.

        :param executor: The AsyncioExecutor passed to is_running_in_executor()
        :return: The result of is_running_in_executor()
        """
        return await AsyncioUtilCallStacks.async_level_2(executor)

    @staticmethod
    async def async_then_sync_level_3(executor: AsyncioExecutor) -> bool:
        """
        Calls is_running_in_executor() 3 synchronous levels below an async method.

        :param executor: The AsyncioExecutor passed to is_running_in_executor()
        :return: The result of is_running_in_executor()
        """
        return AsyncioUtilCallStacks.sync_level_3(executor)

    @staticmethod
    async def async_generator_level_1(executor: AsyncioExecutor) -> AsyncIterator[bool]:
        """
        Yields the result of is_running_in_executor() called directly from an async generator.

        :param executor: The AsyncioExecutor passed to is_running_in_executor()
        :return: An async iterator yielding the result of is_running_in_executor()
        """
        yield AsyncioUtil.is_running_in_executor(executor)

    @staticmethod
    async def async_collect_generator(executor: AsyncioExecutor) -> List[bool]:
        """
        Collects every value yielded by async_generator_level_1().

        :param executor: The AsyncioExecutor passed to is_running_in_executor()
        :return: The list of values yielded by async_generator_level_1()
        """
        results: List[bool] = []
        # Collect every value the async generator yields
        result: bool
        async for result in AsyncioUtilCallStacks.async_generator_level_1(executor):
            results.append(result)
        return results

    # Thread boundaries

    @staticmethod
    async def async_run_in_thread_pool(executor: AsyncioExecutor) -> bool:
        """
        Runs sync_level_3() in the default thread pool of the running event loop.
        The worker thread runs no event loop of its own.

        :param executor: The AsyncioExecutor passed to is_running_in_executor()
        :return: The result of is_running_in_executor() as seen on the worker thread
        """
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, AsyncioUtilCallStacks.sync_level_3, executor)
