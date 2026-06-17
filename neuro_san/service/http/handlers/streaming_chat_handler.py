
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

from http import HTTPStatus

import asyncio
import contextlib
import json
from json.decoder import JSONDecodeError
import time
import tornado

from neuro_san.internals.messages.chat_message_type import ChatMessageType
from neuro_san.service.generic.async_agent_service import AsyncAgentService
from neuro_san.service.http.handlers.base_request_handler import BaseRequestHandler


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
        self.heartbeat_interval_seconds = kwargs.get("heartbeat_interval_seconds", 0)
        # Build the on-the-wire heartbeat frame once at initialize() time so
        # each tick only needs to write bytes -- no per-tick JSON serialization.
        self.heartbeat_frame: str = self._build_heartbeat_frame()
        self.last_send_ts = 0.0
        self.heartbeat_task: asyncio.Task = None

        if self.heartbeat_interval_seconds > 0:
            # If heartbeat is enabled,
            # start the heartbeat task in the background, so it can run concurrently with the main request processing.
            self.heartbeat_task = asyncio.create_task(self.run_heartbeat())

    @staticmethod
    def _build_heartbeat_frame() -> str:
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
    async def post(self, agent_name: str):
        """
        Implementation of POST request handler for streaming chat API call.
        """

        metadata: Dict[str, Any] = self.get_metadata()
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

        result_generator: AsyncGenerator[Dict[str, Any], None] = None

        # Parse the JSON request body separately from everything else.
        request_dict: Dict[str, Any] = None
        try:
            # Parse JSON body
            request_dict = json.loads(self.request.body)
        except JSONDecodeError as exc:
            # Suppress possible exceptions: they are of no interest here.
            with contextlib.suppress(Exception):
                self.process_exception(exc)
            await self._finish_request(result_generator, metadata, agent_name)
            return

        is_event: bool = service.should_process_as_event(request_dict)
        flushed_first_result: bool = False
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

            # Now process the result stream
            async with asyncio.timeout(request_timeout):
                result_generator = service.streaming_chat(request_dict, metadata)
                async for result_dict in result_generator:
                    result_str: str = json.dumps(result_dict) + "\n"
                    self.write(result_str)
                    flush_ok = await self.do_flush()
                    if flush_ok:
                        # Some flush was successful. This is good.
                        flushed_first_result = True
                        # Register the time of the last successful flush, so that we can adjust our heartbeat timing.
                        self.last_send_ts = time.monotonic()
                    else:
                        # We tried flushing the result to no avail
                        if self._is_client_close_a_problem(is_event, flushed_first_result):
                            # Raise exception to be handled as a general
                            # "stream abruptly closed" case:
                            raise tornado.iostream.StreamClosedError()
                        # Otherwise swallow and continue

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
            if self.heartbeat_task is not None:
                self.heartbeat_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self.heartbeat_task
            await self._finish_request(result_generator, metadata, agent_name)

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
                         self.heartbeat_interval_seconds)
        time_to_sleep: float = self.heartbeat_interval_seconds
        while True:
            await asyncio.sleep(time_to_sleep)
            time_now: float = time.monotonic()
            time_to_sleep = self.heartbeat_interval_seconds - (time_now - self.last_send_ts)
            if time_to_sleep > 0.5:
                # We have seen some request traffic recently, so we can delay our heartbeat a bit.
                # Time to sleep is long enough - so go sleep
                continue
            if self._finished:
                # No need to send heartbeats if we are already finished.
                # Time to exit and end the heartbeat task.
                return
            try:
                # self.heartbeat_frame already includes the ChatResponse envelope
                # and a trailing newline (see _build_heartbeat_frame()).
                self.write(self.heartbeat_frame)
                await self.flush()
                self.last_send_ts = time.monotonic()
                time_to_sleep = self.heartbeat_interval_seconds
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
