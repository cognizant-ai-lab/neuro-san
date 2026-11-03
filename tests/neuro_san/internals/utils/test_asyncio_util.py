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
from asyncio import run_coroutine_threadsafe
from concurrent.futures import Future
from typing import Any
from typing import Coroutine

from unittest import IsolatedAsyncioTestCase

from typing_extensions import override

from leaf_common.asyncio.asyncio_executor import AsyncioExecutor

from neuro_san.internals.utils.asyncio_util import AsyncioUtil
from tests.neuro_san.internals.utils.asyncio_util_call_stacks import AsyncioUtilCallStacks


class TestAsyncioUtil(IsolatedAsyncioTestCase):
    """
    Unit tests for AsyncioUtil.is_running_in_executor(), called 1, 2 and 3 levels deep
    from threads with no running event loop, from the test's own event loop,
    and from the event loop of a running AsyncioExecutor.
    Synchronous test methods run without an event loop on their thread.
    Async test methods run on the test's own event loop, which is not the executor's loop.
    """

    # Seconds to wait for a coroutine scheduled on the executor's event loop
    TIMEOUT_SECONDS: float = 10.0

    @override
    def setUp(self) -> None:
        """
        Creates and starts the AsyncioExecutor whose event loop is checked.
        """
        self.executor: AsyncioExecutor = AsyncioExecutor()
        self.executor.start()

    @override
    def tearDown(self) -> None:
        """
        Shuts down the AsyncioExecutor.
        """
        self.executor.shutdown()

    def run_on_executor_loop(self, coroutine: Coroutine[Any, Any, Any]) -> Any:
        """
        Runs a coroutine on the executor's event loop and blocks until it completes.

        :param coroutine: The coroutine to run
        :return: The result of the coroutine
        """
        future: Future = run_coroutine_threadsafe(coroutine, self.executor.get_event_loop())
        return future.result(timeout=self.TIMEOUT_SECONDS)

    # No running event loop

    def test_no_loop_level_1(self) -> None:
        """
        Tests that a direct call from a thread with no running event loop returns False.
        """
        self.assertFalse(AsyncioUtil.is_running_in_executor(self.executor))
        self.assertFalse(AsyncioUtilCallStacks.sync_level_1(self.executor))

    def test_no_loop_level_2(self) -> None:
        """
        Tests that a call 2 levels deep on a thread with no running event loop returns False.
        """
        self.assertFalse(AsyncioUtilCallStacks.sync_level_2(self.executor))

    def test_no_loop_level_3(self) -> None:
        """
        Tests that a call 3 levels deep on a thread with no running event loop returns False.
        """
        self.assertFalse(AsyncioUtilCallStacks.sync_level_3(self.executor))

    # Running event loop that is not the executor's

    async def test_other_loop_async_stacks(self) -> None:
        """
        Tests that async calls 1, 2 and 3 levels deep on a different event loop return False.
        """
        self.assertFalse(AsyncioUtil.is_running_in_executor(self.executor))
        self.assertFalse(await AsyncioUtilCallStacks.async_level_1(self.executor))
        self.assertFalse(await AsyncioUtilCallStacks.async_level_2(self.executor))
        self.assertFalse(await AsyncioUtilCallStacks.async_level_3(self.executor))

    async def test_other_loop_sync_stacks(self) -> None:
        """
        Tests that synchronous calls below an async method on a different event loop return False.
        """
        self.assertFalse(AsyncioUtilCallStacks.sync_level_1(self.executor))
        self.assertFalse(AsyncioUtilCallStacks.sync_level_3(self.executor))

    # Running event loop that is the executor's

    def test_executor_loop_level_1(self) -> None:
        """
        Tests that a direct call from an async method on the executor's event loop returns True.
        """
        self.assertTrue(self.run_on_executor_loop(AsyncioUtilCallStacks.async_level_1(self.executor)))

    def test_executor_loop_level_2(self) -> None:
        """
        Tests that a call 2 async levels deep on the executor's event loop returns True.
        """
        self.assertTrue(self.run_on_executor_loop(AsyncioUtilCallStacks.async_level_2(self.executor)))

    def test_executor_loop_level_3(self) -> None:
        """
        Tests that a call 3 async levels deep on the executor's event loop returns True.
        """
        self.assertTrue(self.run_on_executor_loop(AsyncioUtilCallStacks.async_level_3(self.executor)))

    def test_executor_loop_sync_below_async(self) -> None:
        """
        Tests that a call 3 synchronous levels below an async method on the executor's event loop returns True.
        """
        self.assertTrue(self.run_on_executor_loop(AsyncioUtilCallStacks.async_then_sync_level_3(self.executor)))

    def test_executor_loop_async_generator(self) -> None:
        """
        Tests that a call from an async generator on the executor's event loop returns True.
        """
        self.assertEqual([True],
                         self.run_on_executor_loop(AsyncioUtilCallStacks.async_collect_generator(self.executor)))

    # Thread boundaries

    def test_executor_thread_pool_is_not_loop(self) -> None:
        """
        Tests that a call made on a thread pool worker of the executor's event loop returns False,
        because the worker thread runs no event loop of its own.
        """
        self.assertFalse(self.run_on_executor_loop(AsyncioUtilCallStacks.async_run_in_thread_pool(self.executor)))
