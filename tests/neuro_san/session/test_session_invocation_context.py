
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

from threading import active_count
from time import monotonic
from time import sleep
from unittest import TestCase
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

from leaf_common.asyncio.asyncio_executor_pool import AsyncioExecutorPool

from neuro_san.internals.interfaces.lingering_resource import LingeringResource
from neuro_san.session.session_invocation_context import SessionInvocationContext


class TestSessionInvocationContext(TestCase):
    """
    Tests for the request lifecycle of SessionInvocationContext: finish_request()
    runs at most once per exchange, and reset() starts a new exchange, so a
    DirectAgentSession that is reused across turns returns every executor it
    borrows. Real AsyncioExecutors from a pool that shuts each one down on return
    are used, so the executor threads themselves show whether an exchange closed.
    """

    @staticmethod
    def make_context() -> SessionInvocationContext:
        """
        :return: A started SessionInvocationContext over a non-reusing executor
                 pool, with mock factories that are never called.
        """
        pool: AsyncioExecutorPool = AsyncioExecutorPool(reuse_mode=False)
        context = SessionInvocationContext(agent_name="test_agent",
                                           async_session_factory=MagicMock(),
                                           async_executors_pool=pool,
                                           llm_factory=MagicMock())
        context.start()
        return context

    @staticmethod
    def make_resource() -> LingeringResource:
        """
        :return: A LingeringResource whose close methods record how often they were awaited.
        """
        resource: LingeringResource = MagicMock(spec=LingeringResource)
        resource.close_of_request = AsyncMock()
        resource.close_of_work = AsyncMock()
        return resource

    @staticmethod
    def wait_for_thread_count(limit: int, timeout_seconds: float = 2.0) -> int:
        """
        Waits briefly for the thread count to fall to the given limit, since an
        executor's thread finishes a moment after the pool shuts it down.

        :param limit: The thread count to wait for.
        :param timeout_seconds: How long to keep checking before giving up.
        :return: The last thread count observed.
        """
        deadline: float = monotonic() + timeout_seconds
        count: int = active_count()
        while count > limit and monotonic() < deadline:
            sleep(0.05)
            count = active_count()
        return count

    def test_finish_request_returns_the_executor_once(self) -> None:
        """
        finish_request() returns the executor to the pool, which shuts it down,
        and a second call in the same exchange is a no-op.
        """
        threads_before: int = active_count()
        context: SessionInvocationContext = self.make_context()
        self.assertGreater(active_count(), threads_before)

        context.finish_request()

        self.assertTrue(context.request_finished)
        self.assertIsNone(context.asyncio_executor)
        self.assertLessEqual(self.wait_for_thread_count(threads_before), threads_before)

        # Second call: nothing left to return and no error.
        context.finish_request()
        self.assertIsNone(context.asyncio_executor)

    def test_reset_starts_a_new_exchange_whose_executor_is_returned(self) -> None:
        """
        After a finished exchange, reset() obtains a fresh executor and clears the
        once-only flag, so the next finish_request() returns that executor too
        instead of leaking its thread.
        """
        threads_before: int = active_count()
        context: SessionInvocationContext = self.make_context()
        context.finish_request()

        context.reset()

        self.assertFalse(context.request_finished)
        self.assertIsNotNone(context.asyncio_executor)
        self.assertGreater(active_count(), threads_before)

        context.finish_request()

        self.assertTrue(context.request_finished)
        self.assertIsNone(context.asyncio_executor)
        self.assertLessEqual(self.wait_for_thread_count(threads_before), threads_before)

    def test_reset_drops_resources_only_once_they_were_closed(self) -> None:
        """
        A reset in the middle of an exchange keeps the registered resources, since
        they still need closing. A reset after finish_request() drops them, so the
        next exchange does not close them a second time.
        """
        context: SessionInvocationContext = self.make_context()
        resource: LingeringResource = self.make_resource()
        context.add_resource(resource)

        context.reset()
        self.assertEqual(context.resources, [resource])

        context.finish_request()
        self.assertEqual(resource.close_of_request.await_count, 1)
        self.assertEqual(resource.close_of_work.await_count, 1)

        context.reset()
        self.assertEqual(context.resources, [])

        context.finish_request()
        self.assertEqual(resource.close_of_request.await_count, 1)
        self.assertEqual(resource.close_of_work.await_count, 1)
