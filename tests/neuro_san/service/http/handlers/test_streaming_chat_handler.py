
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

from typing import Any
from typing import AsyncGenerator
from typing import Dict
from typing import List
from typing import Optional

from http import HTTPStatus

import asyncio
import time

from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock
from unittest.mock import Mock
from unittest.mock import patch

import tornado.httpserver
import tornado.netutil
import tornado.web
from typing_extensions import override

from neuro_san.service.http.handlers.streaming_chat_handler import StreamingChatHandler


class TestStreamingChatHandler(IsolatedAsyncioTestCase):
    """
    Tests how StreamingChatHandler behaves when the client drops a streaming_chat request,
    for example when a user presses stop.

    The real handler runs behind a real Tornado server. Only the agent service is replaced
    by a mock that streams slowly, and a raw socket client hangs up after the first chunk.
    """

    MESSAGE_COUNT: int = 40
    MESSAGE_INTERVAL_SECONDS: float = 0.05
    WAIT_SECONDS: float = 10.0
    STREAM_CLOSED_MESSAGE: str = "[%d] Request handler stream closed."

    @override
    async def asyncSetUp(self) -> None:
        """
        Starts a Tornado server around the real handler, with a mock HttpLogger
        so that no global logging configuration is applied.
        """
        logger_patch = patch("neuro_san.service.http.handlers.base_request_handler.HttpLogger")
        self.logger_mock: Mock = logger_patch.start().return_value
        self.addCleanup(logger_patch.stop)

        self.generator_closed: bool = False
        self.service: Mock = Mock()
        self.service.get_request_timeout_seconds.return_value = 0.0
        self.service.streaming_chat.side_effect = self._slow_stream

        service_provider: Mock = Mock()
        service_provider.get_service.return_value = self.service
        agent_policy: Mock = Mock()
        agent_policy.allow_agent = AsyncMock(return_value=(True, service_provider))

        # The three hooks of the neuro-san application that the handler calls
        self.application: tornado.web.Application = tornado.web.Application([
            (r"/api/v1/([^/]+)/streaming_chat", StreamingChatHandler, {
                "forwarded_request_metadata": ["request_id", "user_id"],
                "agent_policy": agent_policy,
            })
        ])
        self.application.is_serving = Mock(return_value=True)
        self.application.try_start_client_request = Mock(return_value=(HTTPStatus.OK, None))
        self.application.finish_client_request = Mock()

        self.server: tornado.httpserver.HTTPServer = tornado.httpserver.HTTPServer(self.application)
        sockets: List[Any] = tornado.netutil.bind_sockets(0, address="127.0.0.1")
        self.server.add_sockets(sockets)
        self.port: int = sockets[0].getsockname()[1]
        self.addAsyncCleanup(self._stop_server)

    async def _stop_server(self) -> None:
        """
        Stops the server and closes any connection that is still open.
        """
        self.server.stop()
        await self.server.close_all_connections()

    async def _slow_stream(self, _request_dict: Dict[str, Any], _metadata: Dict[str, Any]) \
            -> AsyncGenerator[Dict[str, Any], None]:
        """
        Streams one message at a time, slowly enough that the client can hang up in the middle.
        Records whether the handler closed the stream afterward.

        :param _request_dict: the request, which the stream ignores
        :param _metadata: the request metadata, which the stream ignores
        :return: a stream of chat responses
        """
        try:
            index: int = 0
            # Keep streaming until the handler closes this generator
            for index in range(self.MESSAGE_COUNT):
                await asyncio.sleep(self.MESSAGE_INTERVAL_SECONDS)
                yield {"response": {"type": "AI", "text": f"message {index}"}}
        finally:
            self.generator_closed = True

    async def _wait_until_called(self, mock: Mock) -> None:
        """
        Waits for a mock to be called, so the test does not depend on fixed sleeps.

        :param mock: the mock to wait for
        """
        deadline: float = time.monotonic() + self.WAIT_SECONDS
        # Poll until the mock is called or the time is up
        while not mock.called and time.monotonic() < deadline:
            await asyncio.sleep(0.05)
        self.assertTrue(mock.called, "The handler did not finish the request in time.")

    async def _chat_and_hang_up(self, is_event: bool) -> None:
        """
        Sends a streaming_chat request, reads the first chunk and then closes the connection.
        Returns once the handler has finished the request.

        :param is_event: whether the service treats the request as an event
        """
        self.service.should_process_as_event.return_value = is_event
        body: bytes = b'{"user_message": {"text": "hi"}}'
        request: bytes = (b"POST /api/v1/hello_world/streaming_chat HTTP/1.1\r\nHost: localhost\r\n"
                          b"Content-Length: " + str(len(body)).encode() + b"\r\n\r\n" + body)

        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        writer.write(request)
        await writer.drain()
        received: bytes = b""
        # The headers arrive first. Read on until the first message is there too, so the chat is under way
        # and the handler has flushed its first result.
        async with asyncio.timeout(self.WAIT_SECONDS):
            while b"message 0" not in received:
                received += await reader.read(200)
        writer.close()

        await self._wait_until_called(self.application.finish_client_request)

    def _find_info_metadata(self, message: str) -> Optional[Dict[str, Any]]:
        """
        Finds an INFO message that the handler logged.

        :param message: the format string of the message to look for
        :return: the request metadata passed with the first such message, or None if it was not logged
        """
        call: Any = None
        # Look through the INFO messages the handler logged
        for call in self.logger_mock.info.call_args_list:
            if call.args[1] == message:
                return call.args[0]
        return None

    async def test_client_drop_is_not_logged_as_error(self) -> None:
        """A client that hangs up mid-stream is logged at INFO, not as a Tornado ERROR with a stack trace."""
        with self.assertNoLogs("tornado.application", level="ERROR"):
            await self._chat_and_hang_up(is_event=False)

        metadata: Optional[Dict[str, Any]] = self._find_info_metadata(self.STREAM_CLOSED_MESSAGE)
        self.assertIsNotNone(metadata, "The handler did not log that the stream closed.")
        # The record carries a request id, so it can be told apart from other requests
        self.assertTrue(metadata.get("request_id", "None").startswith("request-"))

    async def test_client_drop_still_cleans_up(self) -> None:
        """The service stream is closed and the client request is finished when the client hangs up."""
        await self._chat_and_hang_up(is_event=False)

        self.assertTrue(self.generator_closed)
        self.application.finish_client_request.assert_called_once()

    async def test_event_client_drop_after_first_result_is_silent(self) -> None:
        """An event whose client leaves after the first result is not a problem and logs nothing special."""
        with self.assertNoLogs("tornado.application", level="ERROR"):
            await self._chat_and_hang_up(is_event=True)

        self.assertIsNone(self._find_info_metadata(self.STREAM_CLOSED_MESSAGE))
