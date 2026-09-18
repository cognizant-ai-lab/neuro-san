
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
"""
Regression tests for the streaming-chat executor-loop offload.

StreamingChatHandler.post() now runs the per-message conversion/serialization and
request teardown on the request's dedicated AsyncioExecutor event loop (off the
Tornado main loop), leaving only frame writes on the Tornado side. The pieces that
make this safe are:

  * The driver (_start_driver / _drive_streaming_chat / _drain_executor_cleanup),
    which runs on the executor loop and feeds ready-to-write frames back to the
    Tornado loop over an AsyncCollatingQueue via its loop-agnostic synchronous side.
  * SessionInvocationContext executor injection + ownership handoff, so an injected
    (handler-owned) executor is NOT returned to the pool by the context, except when
    work is deferred to the event work queue - in which case ownership transfers to
    the deferred-work path.

These tests exercise those mechanics directly against a real AsyncioExecutor, since
there is otherwise no coverage on this hot path.
"""

import asyncio
import json

import pytest

from leaf_common.asyncio.asyncio_executor import AsyncioExecutor

from neuro_san.internals.chat.async_collating_queue import AsyncCollatingQueue
from neuro_san.service.http.handlers.streaming_chat_handler import StreamingChatHandler
from neuro_san.session.session_invocation_context import SessionInvocationContext


class FakeService:
    """
    Minimal stand-in for AsyncAgentService exposing just consume_streaming_chat(),
    which is what the handler's driver drives on the executor loop.
    """

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def __init__(self, messages, raise_after=False, delay_seconds=0.0):
        self.messages = messages
        self.raise_after = raise_after
        self.delay_seconds = delay_seconds

    async def consume_streaming_chat(self, request_dict, invocation_context,
                                     response_dict_generator, metadata, do_log, log_marker):
        """Yield the canned messages, optionally slowly, optionally then raise."""
        _ = (request_dict, invocation_context, response_dict_generator, metadata, do_log, log_marker)
        for message in self.messages:
            if self.delay_seconds:
                await asyncio.sleep(self.delay_seconds)
            yield message
        if self.raise_after:
            raise ValueError("boom-from-executor-loop")


class FakePool:
    """Observes return_executor() without any real pool machinery."""

    def __init__(self):
        self.returned = []

    def get_executor(self):
        """The injected path must never pull from the pool."""
        raise AssertionError("injected path must not call get_executor()")

    def return_executor(self, executor):
        """Record the returned executor for the test to assert on."""
        self.returned.append(executor)


def make_handler() -> StreamingChatHandler:
    """
    Build a StreamingChatHandler without running Tornado's RequestHandler.__init__
    (which needs a live Application/request). The driver helpers only touch
    self._driver_exception, so that is all we need to set up.
    """
    handler = object.__new__(StreamingChatHandler)
    # pylint: disable=protected-access
    handler._driver_exception = None
    return handler


def make_injected_context(pool, executor) -> SessionInvocationContext:
    """A SessionInvocationContext with an injected (handler-owned) executor."""
    return SessionInvocationContext(
        agent_name="agent",
        async_session_factory=None,
        async_executors_pool=pool,
        llm_factory=None,
        toolbox_factory=None,
        metadata={},
        reservationist=None,
        port=None,
        effective_invocation="chatbot",
        event_work_queue=None,
        asyncio_executor=executor)


# pylint: disable=protected-access
class TestStreamingChatHandlerExecutorOffload:
    """
    Exercises the cross-loop driver: frames are produced on the executor loop and
    consumed on the (test's) main loop, preserving order and terminating cleanly.
    """

    @pytest.mark.asyncio
    async def test_frames_stream_across_loops_in_order(self):
        """Every consumed message becomes exactly one JSON-Lines frame, in order."""
        handler = make_handler()
        executor = AsyncioExecutor()
        executor.start()
        try:
            messages = [{"response": {"text": f"m{i}"}} for i in range(5)]
            out_queue = AsyncCollatingQueue()
            _task, done = handler._start_driver(
                executor, FakeService(messages), {}, None, None, {}, False, "", out_queue)

            collected = [frame async for frame in out_queue]
            await asyncio.wrap_future(done)

            assert collected == [json.dumps(m) + "\n" for m in messages]
            assert handler._driver_exception is None
        finally:
            executor.shutdown()

    @pytest.mark.asyncio
    async def test_driver_exception_is_captured_and_stream_terminates(self):
        """
        A failure raised on the executor loop is captured for the Tornado side to
        surface, and the output stream still terminates (final item is emitted).
        """
        handler = make_handler()
        executor = AsyncioExecutor()
        executor.start()
        try:
            messages = [{"response": {"text": "only"}}]
            out_queue = AsyncCollatingQueue()
            _task, done = handler._start_driver(
                executor, FakeService(messages, raise_after=True),
                {}, None, None, {}, False, "", out_queue)

            collected = [frame async for frame in out_queue]
            await asyncio.wrap_future(done)

            # The frame produced before the failure still reached the consumer...
            assert collected == [json.dumps(messages[0]) + "\n"]
            # ...and the exception was captured for the handler to re-raise.
            assert isinstance(handler._driver_exception, ValueError)
        finally:
            executor.shutdown()

    @pytest.mark.asyncio
    async def test_cancellation_unblocks_consumer_without_hang(self):
        """
        Cancelling the driver mid-stream (as the handler does on timeout / client
        close) still resolves driver_done and still emits the final item, so the
        Tornado-side consumer never hangs.
        """
        handler = make_handler()
        executor = AsyncioExecutor()
        executor.start()
        try:
            messages = [{"response": {"text": f"m{i}"}} for i in range(1000)]
            out_queue = AsyncCollatingQueue()
            task, done = handler._start_driver(
                executor, FakeService(messages, delay_seconds=0.01),
                {}, None, None, {}, False, "", out_queue)

            # Pull a couple of frames, then cancel the driver on the executor loop.
            await asyncio.wait_for(out_queue.queue.async_q.get(), timeout=5)
            await asyncio.wait_for(out_queue.queue.async_q.get(), timeout=5)
            executor.get_event_loop().call_soon_threadsafe(task.cancel)

            # driver_done must resolve promptly (no hang)...
            await asyncio.wait_for(asyncio.wrap_future(done), timeout=5)
            # ...and iteration must terminate (final item was emitted in the driver's finally).
            remaining = await asyncio.wait_for(
                _collect(out_queue), timeout=5)
            assert isinstance(remaining, list)
        finally:
            executor.shutdown()


async def _collect(out_queue: AsyncCollatingQueue):
    """Drain an AsyncCollatingQueue to completion."""
    return [frame async for frame in out_queue]


# pylint: disable=protected-access
class TestSessionInvocationContextExecutorInjection:
    """
    Verifies the executor injection + ownership handoff that lets the handler own
    the executor's lifecycle.
    """

    def test_injected_executor_is_not_returned_by_context(self):
        """
        An injected executor is not owned by the context: done_with_work() must not
        return it to the pool (the handler does), and construction must not pull from
        the pool.
        """
        pool = FakePool()
        executor = AsyncioExecutor()
        executor.start()
        try:
            context = make_injected_context(pool, executor)
            assert context.owns_executor is False
            assert context.asyncio_executor is executor
            assert context.deferred_to_event_work is False

            context.done_with_work("test")
            assert not pool.returned, "handler-owned executor must not be returned by the context"
        finally:
            executor.shutdown()

    def test_event_deferral_transfers_ownership_and_returns_once(self):
        """
        When work is deferred to the event work queue, ownership transfers to the
        deferred-work path: done_with_work() then returns the (injected) executor
        exactly once.
        """
        pool = FakePool()
        executor = AsyncioExecutor()
        executor.start()
        try:
            context = make_injected_context(pool, executor)
            # Simulate what finish_request() does on the event-deferral branch.
            context.deferred_to_event_work = True
            context.owns_executor = True

            context.done_with_work("test-deferred")
            assert pool.returned == [executor]
        finally:
            executor.shutdown()
