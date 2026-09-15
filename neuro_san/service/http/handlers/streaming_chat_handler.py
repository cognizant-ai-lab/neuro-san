
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
See class comment for details
"""
from typing import Any
from typing import Dict
from typing import AsyncGenerator
from typing import Tuple
from typing import Optional

from http import HTTPStatus

import asyncio
import concurrent.futures
from asyncio import Lock as AsyncLock
import contextlib
import json
from json.decoder import JSONDecodeError
import time
import uuid
import tornado

from leaf_common.asyncio.asyncio_executor import AsyncioExecutor
from leaf_common.asyncio.asyncio_executor_pool import AsyncioExecutorPool

from neuro_san.internals.chat.async_collating_queue import AsyncCollatingQueue
from neuro_san.message.types.chat_message_type import ChatMessageType
from neuro_san.service.generic.async_agent_service import AsyncAgentService
from neuro_san.service.http.handlers.base_request_handler import BaseRequestHandler
from neuro_san.session.session_invocation_context import SessionInvocationContext
from neuro_san.service.utils.http_llm_tracer import HttpxLlmTracer


class StreamingChatHandler(BaseRequestHandler):
    """
    Handler class for neuro-san streaming chat API call.
    """

    # pylint: disable=attribute-defined-outside-init
    def initialize(self, **kwargs):
        """
        This method is called by Tornado framework to allow
        injecting service-specific data into local handler context.
        :param kwargs: dictionary of named parameters, including:
            "heartbeat_interval_seconds" - heartbeat protocol message interval
                in seconds. The heartbeat payload itself is fixed (see
                _build_heartbeat_frame()); only the interval is configurable.
        """
        super().initialize(**kwargs)
        self.keep_alive_interval_seconds = kwargs.get("keep_alive_interval_seconds", 0)
        # Build the on-the-wire heartbeat frame once at initialize() time so
        # each tick only needs to write bytes -- no per-tick JSON serialization.
        self.keep_alive_frame: str = self._build_keep_alive_frame()
        self.last_send_ts = 0.0
        self.keep_alive_task: asyncio.Task = None
        self.lock: AsyncLock = AsyncLock()  # protects request writes to output stream and last_send_ts updates
        # Set by the executor-loop driver when request processing raises there, so the
        # Tornado side can signal it once the output queue has drained.
        self._driver_exception: Exception = None

    @staticmethod
    def _build_keep_alive_frame() -> str:
        """
        Build the exact wire frame to write for each heartbeat tick: an empty
        AGENT_PROGRESS ChatMessage wrapped in the standard ChatResponse
        envelope -- {"response": <chat-message>} -- so clients see the same
        shape as real chat responses. A newline is appended so JSON-Lines
        parsers see a clean frame boundary even when the heartbeat lands
        between two real messages.

        The contents are not user-configurable; only the heartbeat interval is.

        :return: The exact string to write per heartbeat tick.
        """
        chat_message: Dict[str, Any] = {
            "type": ChatMessageType.to_string(ChatMessageType.AGENT_PROGRESS),
            "text": "",
        }
        return json.dumps({"response": chat_message}) + "\n"

    # pylint: disable=too-many-statements
    # pylint: disable=too-many-branches
    # pylint: disable=too-many-locals
    async def post(self, agent_name: str):
        """
        Implementation of POST request handler for streaming chat API call.

        The bulk of request processing - building the session, driving the agent
        message stream, converting each message and serializing it to a wire frame,
        and tearing the request down - runs on the request's dedicated AsyncioExecutor
        event loop, off the Tornado main loop. The Tornado loop is left with only
        "basic actions": the setup preamble that is structurally bound to the Tornado
        request/connection, and writing already-serialized frames to the client.
        """
        metadata: Dict[str, Any] = self.get_metadata()
        req_id: Optional[str] = metadata.get("request_id", None)
        if req_id is None:
            req_id = uuid.uuid4().hex[:8]
        # Tag every outbound LLM call made during this request with a
        # short user_req_id so the HttpxLlmTracer's structured log lines
        # can be grouped for post-run analysis. ContextVar propagates
        # through asyncio + executor bridges, so downstream LLM calls
        # inherit this id automatically. No-op if the tracer is disabled.
        HttpxLlmTracer.set_user_request_id(req_id)

        service: AsyncAgentService = await self.get_service(agent_name, metadata)
        if service is None:
            return

        status_code, err_message = self.application.try_start_client_request(metadata, f"{agent_name}/streaming_chat")
        if status_code != HTTPStatus.OK:
            self.do_finish(status_code, err_message)
            return

        # Set up request timeout if it is specified:
        request_timeout: float = service.get_request_timeout_seconds()
        if request_timeout <= 0.0:
            # For asyncio.timeout(), None means no timeout:
            request_timeout = None

        # Parse the JSON request body separately from everything else.
        request_dict: Dict[str, Any] = None
        try:
            # Parse JSON body
            request_dict = json.loads(self.request.body)
        except JSONDecodeError as exc:
            # Suppress possible exceptions: they are of no interest here.
            with contextlib.suppress(Exception):
                self.process_exception(exc)
            await self._finish_request(None, metadata, agent_name)
            return

        is_event: bool = service.should_process_as_event(request_dict)

        # Pull the request's AsyncioExecutor UP to the handler: obtain it here and start
        # it (a no-op for a pooled/reused executor). We own returning it to the pool,
        # except when the request defers work to the event work queue - in which case
        # ownership transfers to that deferred path (see SessionInvocationContext).
        pool: AsyncioExecutorPool = self.server_context.get_executor_pool()
        executor: AsyncioExecutor = pool.get_executor()
        executor.start()

        # Synchronous setup stays on the Tornado thread: SessionInvocationContext.start()
        # performs a blocking initialize() wait against the executor loop, which would
        # self-deadlock if it ran from the executor loop thread itself.
        try:
            invocation_context, response_dict_generator, service_metadata, do_log, log_marker = \
                service.prepare_streaming_chat(request_dict, metadata, asyncio_executor=executor)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            with contextlib.suppress(Exception):
                self.process_exception(exc)
            pool.return_executor(executor)
            await self._finish_request(None, metadata, agent_name)
            return

        # One output queue carrying ready-to-write wire frames (strings). Its async side
        # binds to THIS (Tornado) loop - the write side. The driver on the executor loop
        # feeds it via the loop-agnostic synchronous side.
        out_queue: AsyncCollatingQueue = AsyncCollatingQueue()
        self._driver_exception = None

        # Drive per-message conversion/serialization and teardown on the executor loop.
        driver_task, driver_done = self._start_driver(
            executor, service, request_dict, invocation_context,
            response_dict_generator, service_metadata, do_log, log_marker, out_queue)

        flushed_first_result: bool = False
        client_gone: bool = False
        try:
            # Set up headers for chunked response
            self.set_header("Content-Type", "application/json-lines")
            self.set_header("Transfer-Encoding", "chunked")

            # Flush headers immediately
            flush_ok: bool = await self.do_flush()
            if not flush_ok:
                # If we failed to flush our output,
                # most probably it's because connection is closed by a client.
                # Raise accordingly - we will handle this exception:
                raise tornado.iostream.StreamClosedError()

            # We are now ready to start streaming results back to the client.
            # If heartbeat is enabled, time to start it here:
            if self.keep_alive_interval_seconds > 0:
                # Start the heartbeat task in the background,
                # so it can run concurrently with the main request processing.
                self.keep_alive_task = asyncio.create_task(self.run_heartbeat())

            # Consume ready-to-write frames produced on the executor loop and send them.
            async with asyncio.timeout(request_timeout):
                async for result_str in out_queue:
                    if client_gone:
                        # The client is gone but the work is allowed to finish on the
                        # executor loop (e.g. an event agent). Drain frames without
                        # writing so the driver can complete and memory stays bounded.
                        continue
                    async with self.lock:
                        self.write(result_str)
                        flush_ok = await self.do_flush()
                        self.last_send_ts = time.monotonic()
                    if flush_ok:
                        # Some flush was successful. This is good.
                        flushed_first_result = True
                    else:
                        # We tried flushing the result to no avail
                        if self._is_client_close_a_problem(is_event, flushed_first_result):
                            # Raise exception to be handled as a general
                            # "stream abruptly closed" case:
                            raise tornado.iostream.StreamClosedError()
                        # Event agent, first result already out: stop writing but let the
                        # work complete on the executor loop.
                        client_gone = True

            # Stream drained normally; surface any exception raised on the executor loop.
            if self._driver_exception is not None:
                raise self._driver_exception

        except asyncio.CancelledError:
            self.logger.info(metadata, "Request handler cancelled.")
            # Re-raise as recommended
            raise

        except tornado.iostream.StreamClosedError:
            if self._is_client_close_a_problem(is_event, flushed_first_result):
                self.logger.info(metadata, "Request handler stream closed.")
                # Re-raise as recommended
                raise

            # Swallow. For event agents, it's ok if the client goes away before processing is done.

        except asyncio.TimeoutError:
            self.logger.info(metadata, "Chat request timeout for %s in %f seconds.", agent_name, request_timeout)
            # Recommended HTTP response code: Service Unavailable
            self.set_status(HTTPStatus.SERVICE_UNAVAILABLE)
            self.write({"error": "Request timeout"})

        except Exception as exc:  # pylint: disable=broad-exception-caught
            # Suppress possible exceptions: they are of no interest here.
            with contextlib.suppress(Exception):
                self.process_exception(exc)

        finally:
            # If we started a heartbeat task, cancel it now to clean up resources.
            if self.keep_alive_task is not None:
                self.keep_alive_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self.keep_alive_task

            # If the driver is still running (timeout, problematic client close, or an
            # unexpected error left the consume loop early), cancel it on the executor loop.
            if not driver_task.done():
                executor.get_event_loop().call_soon_threadsafe(driver_task.cancel)

            # Wait for the driver to fully finish - including its teardown - before deciding
            # the executor's fate. This also settles the deferred_to_event_work flag.
            with contextlib.suppress(Exception):
                await asyncio.wrap_future(driver_done)

            await self._finish_request(None, metadata, agent_name)

            # Return the executor to the pool unless the request deferred work to the event
            # work queue, in which case the deferred-work path now owns returning it.
            if not invocation_context.deferred_to_event_work:
                pool.return_executor(executor)

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def _start_driver(self, executor: AsyncioExecutor, service: AsyncAgentService,
                      request_dict: Dict[str, Any], invocation_context: SessionInvocationContext,
                      response_dict_generator: AsyncGenerator[Dict[str, Any], None],
                      service_metadata: Dict[str, str], do_log: bool, log_marker: str,
                      out_queue: AsyncCollatingQueue) \
            -> Tuple[asyncio.Task, concurrent.futures.Future]:
        """
        Submit the streaming driver coroutine onto the executor loop and bridge its
        completion back to the Tornado loop.

        :return: A tuple of (driver_task, driver_done) where driver_task is the
                 asyncio.Task on the executor loop (used to cancel it) and driver_done
                 is a concurrent.futures.Future the driver resolves when it finishes
                 (awaitable from the Tornado loop via asyncio.wrap_future). The driver
                 resolves the future itself rather than via a done-callback, since
                 asyncio.Task.add_done_callback is not safe to call cross-thread.
        """
        driver_done: concurrent.futures.Future = concurrent.futures.Future()
        driver_task: asyncio.Task = executor.create_task(
            self._drive_streaming_chat(
                service, request_dict, invocation_context, response_dict_generator,
                service_metadata, do_log, log_marker, out_queue, driver_done),
            "streaming_chat_driver")
        return driver_task, driver_done

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    async def _drive_streaming_chat(self, service: AsyncAgentService,
                                    request_dict: Dict[str, Any],
                                    invocation_context: SessionInvocationContext,
                                    response_dict_generator: AsyncGenerator[Dict[str, Any], None],
                                    service_metadata: Dict[str, str], do_log: bool, log_marker: str,
                                    out_queue: AsyncCollatingQueue,
                                    driver_done: concurrent.futures.Future):
        """
        Runs on the executor loop. Consumes the converted response stream, serializes
        each message to a wire frame, and feeds it to the output queue for the Tornado
        loop to write. On completion it drains any in-flight teardown tasks so the
        handler can return the executor to the pool without cancelling live cleanup,
        and resolves driver_done so the Tornado side can await our completion.
        """
        cancelled: bool = False
        try:
            async for response_dict in service.consume_streaming_chat(
                    request_dict, invocation_context, response_dict_generator,
                    service_metadata, do_log, log_marker):
                result_str: str = json.dumps(response_dict) + "\n"
                # synchronous=True: the get()-ing end lives on the Tornado loop.
                await out_queue.put(result_str, synchronous=True)
        except asyncio.CancelledError:
            # The handler cancelled us (timeout or the client went away). consume's own
            # finally has already finalized the request; skip the (best-effort) drain.
            cancelled = True
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # Surface the failure to the Tornado side, which will react after the queue drains.
            self._driver_exception = exc
        finally:
            if not cancelled:
                # Let teardown tasks scheduled by finish_request() (close_of_request /
                # close_of_work) finish before we signal done, so the handler's
                # return_executor() does not cancel live cleanup.
                with contextlib.suppress(Exception):
                    await self._drain_executor_cleanup()
            # Always unblock the Tornado-side consumer, however we got here.
            with contextlib.suppress(Exception):
                await out_queue.put_final_item(synchronous=True)
            # Signal our completion to the Tornado side (awaited via asyncio.wrap_future).
            if not driver_done.done():
                driver_done.set_result(True)

    @staticmethod
    async def _drain_executor_cleanup():
        """
        Await all tasks currently pending on this (executor) loop except the caller,
        so that fire-and-forget teardown scheduled during request finalization runs to
        completion. Each request owns its executor exclusively while checked out of the
        pool, so these tasks all belong to this request.
        """
        current: asyncio.Task = asyncio.current_task()
        pending = [task for task in asyncio.all_tasks() if task is not current]
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)

    async def run_heartbeat(self):
        """
        Background task driving the HTTP heartbeat: every
        heartbeat_interval_seconds (and only when no real traffic has been
        flushed within that window), write the pre-built heartbeat frame
        to keep proxies/clients from dropping the streaming connection.
        Exits when the request finishes or the client disconnects.
        """
        metadata: Dict[str, Any] = self.get_metadata()
        self.logger.info(metadata, "Starting heartbeat generator with interval %d seconds",
                         self.keep_alive_interval_seconds)
        time_to_sleep: float = self.keep_alive_interval_seconds
        while True:
            await asyncio.sleep(time_to_sleep)
            time_now: float = time.monotonic()
            time_to_sleep = self.keep_alive_interval_seconds - (time_now - self.last_send_ts)
            if time_to_sleep > 0.5:
                # We have seen some request traffic recently, so we can delay our heartbeat a bit.
                # Time to sleep is long enough - so go sleep
                continue
            try:
                # self.heartbeat_frame already includes the ChatResponse envelope
                # and a trailing newline (see _build_heartbeat_frame()).
                async with self.lock:
                    self.write(self.keep_alive_frame)
                    flush_ok = await self.do_flush()
                    self.last_send_ts = time.monotonic()
                if not flush_ok:
                    # We tried flushing the heartbeat with no success
                    # (most probably because connection is closed by a client).
                    # Finish heartbeat task
                    return
                time_to_sleep = self.keep_alive_interval_seconds
            except tornado.iostream.StreamClosedError:
                return  # client gone; main loop's next flush will see it too

    def _is_client_close_a_problem(self, is_event: bool, flushed_first_result: bool) -> bool:
        """
        For the most part a client close is a problem and we want to stop processing early.
        Even if this is an event agent, and we have not yet flushed first result, this is still a problem.
        However, if this is an agent invoked as an event, this is not a problem
        as long as we have flushed the first result.
        """
        return not is_event or (is_event and not flushed_first_result)

    async def _finish_request(self, result_generator: AsyncGenerator[Dict[str, Any], None],
                              metadata: Dict[str, Any], agent_name: str):
        # We are done with response stream,
        # ensure generator is closed properly in any case:
        if result_generator is not None:
            with contextlib.suppress(Exception):
                # It is possible we will call .aclose() twice
                # on our result_generator - it is allowed and has no effect.
                await result_generator.aclose()
        self.do_finish()
        self.application.finish_client_request(metadata, f"{agent_name}/streaming_chat", get_stats=True)
