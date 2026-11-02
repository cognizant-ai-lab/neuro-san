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
from typing import List

from unittest import IsolatedAsyncioTestCase

from typing_extensions import override

from neuro_san.internals.utils.asyncio_util import AsyncioUtil
from tests.neuro_san.internals.utils.asyncio_util_call_stacks import AsyncioUtilCallStacks


class TestAsyncioUtil(IsolatedAsyncioTestCase):
    """
    Unit tests for AsyncioUtil.is_called_by_async_method(), called 1, 2 and 3 levels deep
    from purely synchronous call stacks and from call stacks that contain an async method.
    Synchronous test methods run without an event loop, so their stacks contain no async frames.
    """

    @override
    def setUp(self) -> None:
        """
        Creates the call stack helper.
        """
        self.stacks: AsyncioUtilCallStacks = AsyncioUtilCallStacks()

    # Purely synchronous call stacks

    def test_sync_stack_level_1(self) -> None:
        """
        Tests that a direct call from a synchronous method returns False.
        """
        self.assertFalse(AsyncioUtil.is_called_by_async_method())
        self.assertFalse(self.stacks.sync_level_1())

    def test_sync_stack_level_2(self) -> None:
        """
        Tests that a call 2 levels deep in a synchronous stack returns False.
        """
        self.assertFalse(self.stacks.sync_level_2())

    def test_sync_stack_level_3(self) -> None:
        """
        Tests that a call 3 levels deep in a synchronous stack returns False.
        """
        self.assertFalse(self.stacks.sync_level_3())

    def test_sync_method_kinds(self) -> None:
        """
        Tests that synchronous instance and class methods return False.
        """
        self.assertFalse(self.stacks.sync_instance_level_1())
        self.assertFalse(AsyncioUtilCallStacks.sync_class_level_1())

    # Call stacks of async methods only

    async def test_async_stack_level_1(self) -> None:
        """
        Tests that a direct call from an async method returns True.
        """
        self.assertTrue(AsyncioUtil.is_called_by_async_method())
        self.assertTrue(await self.stacks.async_level_1())

    async def test_async_stack_level_2(self) -> None:
        """
        Tests that a call 2 levels deep in an all-async stack returns True.
        """
        self.assertTrue(await self.stacks.async_level_2())

    async def test_async_stack_level_3(self) -> None:
        """
        Tests that a call 3 levels deep in an all-async stack returns True.
        """
        self.assertTrue(await self.stacks.async_level_3())

    async def test_async_method_kinds(self) -> None:
        """
        Tests that async instance methods, class methods and async generators return True.
        """
        self.assertTrue(await self.stacks.async_instance_level_1())
        self.assertTrue(await AsyncioUtilCallStacks.async_class_level_1())

        results: List[bool] = []
        # Collect every value the async generator yields
        result: bool
        async for result in self.stacks.async_generator_level_1():
            results.append(result)
        self.assertEqual([True], results)

    # Async test methods calling through synchronous methods

    async def test_async_then_sync_level_1(self) -> None:
        """
        Tests that a synchronous method called directly by an async method returns True.
        """
        self.assertTrue(self.stacks.sync_level_1())

    async def test_async_then_sync_level_2(self) -> None:
        """
        Tests that a call 2 synchronous levels below an async method returns True.
        """
        self.assertTrue(self.stacks.sync_level_2())

    async def test_async_then_sync_level_3(self) -> None:
        """
        Tests that a call 3 synchronous levels below an async method returns True.
        """
        self.assertTrue(self.stacks.sync_level_3())

    # Thread boundaries

    def test_executor_thread_is_sync(self) -> None:
        """
        Tests that a synchronous call made on an executor thread returns False,
        because the async caller is on a different thread's call stack.
        """
        self.assertFalse(self.stacks.sync_in_executor())
