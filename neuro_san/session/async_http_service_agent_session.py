
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
from typing import Dict
from typing import Generator
from typing import Optional

import asyncio
import json

from threading import Lock
from contextlib import suppress

from aiohttp import ClientPayloadError
from aiohttp import ClientOSError
from aiohttp import ClientResponse
from aiohttp import ClientSession
from aiohttp import ClientTimeout

from neuro_san.message.utils.decode_utils import DecodeUtils
from neuro_san.interfaces.async_agent_session import AsyncAgentSession
from neuro_san.session.abstract_http_service_agent_session import AbstractHttpServiceAgentSession
from neuro_san.session.agent_session_closed_error import AgentSessionClosedError


class AsyncHttpServiceAgentSession(AbstractHttpServiceAgentSession, AsyncAgentSession):
    """
    Implementation of AsyncAgentSession that talks to an HTTP service.

    A session is single-use with respect to close(): after close() (typically
    called to cancel an in-flight streaming_chat()) the session is closed and any
    further streaming_chat()/function()/connectivity() call raises
    AgentSessionClosedError.
    """

    def __init__(self, *args, **kwargs):
        """
        Constructor. Delegates all connection parameters to the base class and
        adds cancellation state so an in-flight streaming_chat() can be aborted
        via close(). aiohttp objects are bound to their event loop and are not
        thread-safe, so close() schedules the actual close on that loop.
        """
        super().__init__(*args, **kwargs)
        # Guards the cancellation state below against concurrent access.
        self._stream_lock: Lock = Lock()
        # Empirically, aborting an aiohttp request needs different handles in
        # different phases: closing the RESPONSE unblocks an in-flight read after
        # headers have arrived, while closing the SESSION aborts a request still
        # awaiting headers (there may be no total timeout). We track both so
        # close() can cover either window.
        self._active_response: Optional[ClientResponse] = None
        # The aiohttp client session of the in-flight request, if any.
        self._active_session: Optional[ClientSession] = None
        # The event loop the streaming request is running on, so close() can
        # schedule the aiohttp close on the correct (owning) loop.
        self._active_loop: Optional[asyncio.AbstractEventLoop] = None
        # Once closed, no further streaming request will be started.
        self._closed: bool = False

    async def function(self, request_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        :param request_dict: A dictionary version of the FunctionRequest
                    protobufs structure. Has the following keys:
                        <None>
        :return: A dictionary version of the FunctionResponse
                    protobufs structure. Has the following keys:
                "function" - the dictionary description of the function
        """
        self._raise_if_closed()
        path: str = self.get_request_path("function")
        result_dict: Dict[str, Any] = None
        timeout: ClientTimeout = None
        try:
            if self.timeout_in_seconds is not None:
                timeout = ClientTimeout(self.timeout_in_seconds)

            async with ClientSession(headers=self.get_headers(),
                                     timeout=timeout
                                     ) as session:
                async with session.get(path, json=request_dict) as response:
                    result_dict = await response.json()
                    return result_dict
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise ValueError(self.help_message(path)) from exc

    async def connectivity(self, request_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        :param request_dict: A dictionary version of the ConnectivityRequest
                    protobufs structure. Has the following keys:
                        <None>
        :return: A dictionary version of the ConnectivityResponse
                    protobufs structure. Has the following keys:
                "connectivity_info" - the list of connectivity descriptions for
                                    each node in the agent network the service
                                    wants the client ot know about.
        """
        self._raise_if_closed()
        path: str = self.get_request_path("connectivity")
        result_dict: Dict[str, Any] = None
        timeout: ClientTimeout = None
        try:
            if self.timeout_in_seconds is not None:
                timeout = ClientTimeout(self.timeout_in_seconds)
            async with ClientSession(headers=self.get_headers(),
                                     timeout=timeout
                                     ) as session:
                async with session.get(path, json=request_dict) as response:
                    result_dict = await response.json()
                    return result_dict
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise ValueError(self.help_message(path)) from exc

    # pylint: disable=too-many-locals
    async def streaming_chat(self, request_dict: Dict[str, Any]) -> Generator[Dict[str, Any], None, None]:
        """
        :param request_dict: A dictionary version of the ChatRequest
                    protobufs structure. Has the following keys:
            "user_message" - A ChatMessage dict representing the user input to the chat stream
            "chat_context" - A ChatContext dict representing the state of the previous conversation
                            (if any)
        :return: An iterator of dictionary versions of the ChatResponse
                    protobufs structure. Has the following keys:
            "response"      - An optional ChatMessage dictionary.  See chat.proto for details.

            Note that responses to the chat input might be numerous and will come as they
            are produced until the system decides there are no more messages to be sent.
        """
        # pylint: disable=too-many-branches,too-many-statements
        separator: bytes = b"\n"
        max_chunk_size: int = 64 * 1024
        path: str = self.get_request_path("streaming_chat")
        accumulator: bytearray = bytearray(b"")
        index: int = 0
        unicode_line: str = ""

        # A closed session is single-use: fail loudly rather than yielding an
        # empty stream that looks like "the agent returned no messages".
        self._raise_if_closed()
        # Record the running loop now so close() from another thread can schedule
        # the abort even while we are still awaiting response headers.
        with self._stream_lock:
            self._active_loop = asyncio.get_running_loop()

        # To specify complete timeout value, we must use "total" parameter of ClientTimeout.
        # See https://docs.aiohttp.org/en/stable/client_reference.html#aiohttp.ClientTimeout for details.
        timeout: ClientTimeout = ClientTimeout(total=None)
        # That will make sure that the connection will stay open until the (last) result is yielded,
        # which is what we want here.
        # Not specifying "total" parameter will invoke lower-level aiohttp timeout, which is 300 seconds by default
        if self.streaming_timeout_in_seconds is not None:
            timeout = ClientTimeout(total=self.streaming_timeout_in_seconds)

        session: ClientSession = ClientSession(headers=self.get_headers(), timeout=timeout)
        # Track the session BEFORE issuing the request so close() can abort it even
        # while it is still awaiting response headers. If close() raced in between
        # the check above and here, tear the session down and bail.
        abort: bool = False
        with self._stream_lock as next_with:
            _ = next_with
            if self._closed:
                abort = True
            else:
                self._active_session = session
        if abort:
            # close() raced in after our initial check; tear down and fail loudly.
            await session.close()
            raise AgentSessionClosedError("async HTTP agent session has been closed")

        try:
            async with session:
                async with session.post(path, json=request_dict) as response:
                    # Check for successful response status
                    response.raise_for_status()

                    # Headers have arrived; track the response so close() can
                    # unblock the read below (closing the session alone does not).
                    with self._stream_lock:
                        if self._closed:
                            raise AgentSessionClosedError("async HTTP agent session has been closed")
                        self._active_response = response

                    # Iterate over the content stream as it comes in.
                    # Note: We used to iterate over lines with the simpler:
                    #           async for line in response.content:
                    #               ... blah blah ...
                    #       but that could fail with ValueError("Chunk too big")
                    #       if a single line was too long.
                    async for data in response.content.iter_chunked(max_chunk_size):

                        # Concatenate data as it comes in
                        accumulator.extend(data)

                        # Try to find our line separator
                        index = accumulator.find(separator)
                        while index >= 0:

                            # Grab a single line
                            single_line_bytes: bytearray = accumulator[:index]
                            unicode_line = DecodeUtils.decode(single_line_bytes, "utf-8")
                            unicode_line = unicode_line.strip()
                            if unicode_line:    # Skip empty lines
                                # We have a line with something in it.
                                # Decode and yield as a dictionary
                                result_dict: Dict[str, Any] = json.loads(unicode_line)
                                yield result_dict

                            # Remove the previous line from the accumulator
                            del accumulator[:index + len(separator)]

                            # Allow for case of multiple lines in one chunk
                            index = accumulator.find(separator)

                    # If there is anything left in the accumulator, yield it
                    if len(accumulator) > 0:
                        unicode_line = DecodeUtils.decode(accumulator, "utf-8")
                        unicode_line = unicode_line.strip()
                        if unicode_line:
                            result_dict: Dict[str, Any] = json.loads(unicode_line)
                            yield result_dict

        except (asyncio.TimeoutError, ClientOSError, ClientPayloadError) as exc:
            if self.is_closed():
                # Interrupted by a deliberate close(), not a real failure.
                raise AgentSessionClosedError(
                    "async HTTP agent session was closed during streaming_chat()") from exc
            # Pass on a couple of asserts that are known to represent
            # real problems that a client has to deal with.
            # We figure this is OK for streaming_chat() because normally
            # in order to get to using streaming_chat() clients will most
            # often call function() first, and that will have the blanket
            # helpful asserts for the newly initiated.
            raise exc

        except Exception as exc:  # pylint: disable=broad-exception-caught
            if self.is_closed():
                # Interrupted by a deliberate close() from another thread; raise a
                # dedicated error so callers can tell cancellation from a lost
                # connection.
                raise AgentSessionClosedError(
                    "async HTTP agent session was closed during streaming_chat()") from exc
            # Assume the newly initiated need some more help.
            raise ValueError(self.help_message(path)) from exc
        finally:
            # The request is over (normally, by error, or because close() aborted
            # it); stop tracking it.
            with self._stream_lock:
                self._active_response = None
                self._active_session = None
                self._active_loop = None

    def is_closed(self) -> bool:
        """:return: True if close() has been called on this session."""
        with self._stream_lock:
            return self._closed

    def _raise_if_closed(self):
        """Raise AgentSessionClosedError if this session has been closed."""
        if self.is_closed():
            raise AgentSessionClosedError("async HTTP agent session has been closed")

    def close(self):
        """
        Close this session by aborting any in-flight streaming request.

        Marks the session closed and, on the event loop the request runs on,
        aborts it so streaming_chat() unblocks on the client side. Both handles
        are needed because aiohttp aborts differently per phase: closing the
        response unblocks an in-flight read after headers have arrived, while
        closing the session aborts a request still awaiting headers (there may be
        no total timeout). aiohttp objects are bound to their loop and are not
        thread-safe, so the work is scheduled on that loop. Safe to call from
        another thread than the one running streaming_chat(), and safe to call
        more than once.

        Server-side scope: close() releases the client connection; it does NOT
        directly cancel the server-side work. The neuro-san service ends the
        corresponding request only when it next detects the dropped connection --
        on its next result or heartbeat flush. That is prompt while results stream
        (or a keep-alive heartbeat is enabled), but a request producing no output
        with heartbeat and request-timeout disabled may keep running server-side
        until it does.
        """
        response: Optional[ClientResponse] = None
        session: Optional[ClientSession] = None
        loop: Optional[asyncio.AbstractEventLoop] = None
        with self._stream_lock:
            self._closed = True
            response = self._active_response
            session = self._active_session
            loop = self._active_loop
            self._active_response = None
            self._active_session = None
            self._active_loop = None
        if loop is None or loop.is_closed():
            # No running loop to schedule on; best-effort synchronous response close.
            if response is not None:
                with suppress(Exception):
                    response.close()
            return
        # RuntimeError is raised only if the loop is not running -- nothing to abort.
        with suppress(RuntimeError) as next_with:
            _ = next_with
            if response is not None:
                # ClientResponse.close() is synchronous; run it on the owning loop.
                # Unblocks an in-flight read once headers have arrived.
                loop.call_soon_threadsafe(response.close)
            if session is not None:
                # ClientSession.close() is a coroutine; run it on the owning loop.
                # Aborts a request still awaiting headers.
                asyncio.run_coroutine_threadsafe(self._close_session(session), loop)

    @staticmethod
    async def _close_session(session: ClientSession):
        """Close the aiohttp session on its owning loop; swallows teardown errors."""
        with suppress(Exception):
            if not session.closed:
                await session.close()
