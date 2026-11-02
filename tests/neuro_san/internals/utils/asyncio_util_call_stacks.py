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

from neuro_san.internals.utils.asyncio_util import AsyncioUtil


class AsyncioUtilCallStacks:
    """
    Test helper that builds synchronous and asynchronous call stacks of varying depth,
    each ending in a call to AsyncioUtil.is_called_by_async_method().
    """

    # Synchronous call stacks

    @staticmethod
    def sync_level_1() -> bool:
        """
        Calls is_called_by_async_method() directly from a synchronous method.

        :return: The result of is_called_by_async_method()
        """
        return AsyncioUtil.is_called_by_async_method()

    @staticmethod
    def sync_level_2() -> bool:
        """
        Calls is_called_by_async_method() through one intermediate synchronous method.

        :return: The result of is_called_by_async_method()
        """
        return AsyncioUtilCallStacks.sync_level_1()

    @staticmethod
    def sync_level_3() -> bool:
        """
        Calls is_called_by_async_method() through two intermediate synchronous methods.

        :return: The result of is_called_by_async_method()
        """
        return AsyncioUtilCallStacks.sync_level_2()

    def sync_instance_level_1(self) -> bool:
        """
        Calls is_called_by_async_method() directly from a synchronous instance method.

        :return: The result of is_called_by_async_method()
        """
        return AsyncioUtil.is_called_by_async_method()

    @classmethod
    def sync_class_level_1(cls) -> bool:
        """
        Calls is_called_by_async_method() directly from a synchronous class method.

        :return: The result of is_called_by_async_method()
        """
        return AsyncioUtil.is_called_by_async_method()

    # Asynchronous call stacks

    @staticmethod
    async def async_level_1() -> bool:
        """
        Calls is_called_by_async_method() directly from an async method.

        :return: The result of is_called_by_async_method()
        """
        return AsyncioUtil.is_called_by_async_method()

    @staticmethod
    async def async_level_2() -> bool:
        """
        Calls is_called_by_async_method() through one intermediate async method.

        :return: The result of is_called_by_async_method()
        """
        return await AsyncioUtilCallStacks.async_level_1()

    @staticmethod
    async def async_level_3() -> bool:
        """
        Calls is_called_by_async_method() through two intermediate async methods.

        :return: The result of is_called_by_async_method()
        """
        return await AsyncioUtilCallStacks.async_level_2()

    async def async_instance_level_1(self) -> bool:
        """
        Calls is_called_by_async_method() directly from an async instance method.

        :return: The result of is_called_by_async_method()
        """
        return AsyncioUtil.is_called_by_async_method()

    @classmethod
    async def async_class_level_1(cls) -> bool:
        """
        Calls is_called_by_async_method() directly from an async class method.

        :return: The result of is_called_by_async_method()
        """
        return AsyncioUtil.is_called_by_async_method()

    @staticmethod
    async def async_generator_level_1() -> AsyncIterator[bool]:
        """
        Yields the result of is_called_by_async_method() called directly from an async generator.

        :return: An async iterator yielding the result of is_called_by_async_method()
        """
        yield AsyncioUtil.is_called_by_async_method()

    # Thread boundaries

    @staticmethod
    def sync_in_executor() -> bool:
        """
        Runs sync_level_3() on an executor thread from within a new event loop.
        The worker thread has its own call stack, which contains no async frames.

        :return: The result of is_called_by_async_method() as seen on the worker thread
        """
        return asyncio.run(AsyncioUtilCallStacks.async_run_in_executor())

    @staticmethod
    async def async_run_in_executor() -> bool:
        """
        Runs sync_level_3() in the default executor.

        :return: The result of is_called_by_async_method() as seen on the worker thread
        """
        loop: asyncio.AbstractEventLoop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, AsyncioUtilCallStacks.sync_level_3)
