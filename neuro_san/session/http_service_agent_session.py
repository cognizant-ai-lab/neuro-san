
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

import json

from threading import Lock
from contextlib import suppress

import requests

from neuro_san.interfaces.agent_session import AgentSession
from neuro_san.session.abstract_http_service_agent_session import AbstractHttpServiceAgentSession
from neuro_san.session.agent_session_closed_error import AgentSessionClosedError


class HttpServiceAgentSession(AbstractHttpServiceAgentSession, AgentSession):
    """
    Implementation of AgentSession that talks to an HTTP service.
    This is largely only used by command-line tests.

    A session is single-use with respect to close(): after close() (typically
    called from another thread to cancel an in-flight streaming_chat()) the
    session is closed and any further streaming_chat()/function()/connectivity()
    call raises AgentSessionClosedError.
    """

    def is_closed(self) -> bool:
        """:return: True if close() has been called on this session."""
        with self._stream_lock:
            return self._closed

    def _raise_if_closed(self):
        """Raise AgentSessionClosedError if this session has been closed."""
        if self.is_closed():
            raise AgentSessionClosedError("HTTP agent session has been closed")

    def __init__(self, *args, **kwargs):
        """
        Constructor. Delegates all connection parameters to the base class and
        adds cancellation state so an in-flight streaming_chat() can be aborted
        from another thread via close().
        """
        super().__init__(*args, **kwargs)
        # Guards _active_response / _closed against concurrent access between the
        # thread iterating streaming_chat() and a thread calling close().
        self._stream_lock: Lock = Lock()
        # The response of the currently-streaming request, if any, so close()
        # can drop its connection and unblock the streaming read.
        self._active_response: Optional[requests.Response] = None
        # Once closed, no further streaming request will be started.
        self._closed: bool = False

    def function(self, request_dict: Dict[str, Any]) -> Dict[str, Any]:
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
        try:
            response = requests.get(path, json=request_dict, headers=self.get_headers(),
                                    timeout=self.timeout_in_seconds)
            result_dict = json.loads(response.text)
            return result_dict
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise ValueError(self.help_message(path)) from exc

    def connectivity(self, request_dict: Dict[str, Any]) -> Dict[str, Any]:
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
        try:
            response = requests.get(path, json=request_dict, headers=self.get_headers(),
                                    timeout=self.timeout_in_seconds)
            result_dict = json.loads(response.text)
            return result_dict
        except Exception as exc:  # pylint: disable=broad-exception-caught
            raise ValueError(self.help_message(path)) from exc

    def streaming_chat(self, request_dict: Dict[str, Any]) -> Generator[Dict[str, Any], None, None]:
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
        separator: bytes = b"\n"
        max_chunk_size: int = 64 * 1024
        path: str = self.get_request_path("streaming_chat")

        # A closed session is single-use: fail loudly rather than yielding an
        # empty stream that looks like "the agent returned no messages".
        self._raise_if_closed()

        try:
            with requests.post(path, json=request_dict, headers=self.get_headers(),
                               stream=True,
                               timeout=self.streaming_timeout_in_seconds) as response:
                response.raise_for_status()

                # Register this response so close() (possibly from another thread)
                # can drop the connection and unblock the read loop below.
                # If the session was already closed, abort before consuming any stream.
                with self._stream_lock:
                    if self._closed:
                        raise AgentSessionClosedError("HTTP agent session has been closed")
                    self._active_response = response

                # Iterate over the content stream as it comes in.
                # Note: We used to iterate over lines with the simpler:
                #           for line in response.iter_lines(decode_unicode=True):
                #               ...
                #       but that delegated UTF-8 handling to the response's
                #       Content-Type charset (which the server may not set),
                #       and split on universal newlines instead of strict "\n".
                #       We now buffer raw bytes, split strictly on "\n",
                #       and decode UTF-8 explicitly -- mirroring the async client.
                accumulator: bytearray = bytearray(b"")
                for data in response.iter_content(chunk_size=max_chunk_size):

                    # Concatenate data as it comes in
                    accumulator.extend(data)

                    # Try to find our line separator
                    index: int = accumulator.find(separator)
                    while index >= 0:

                        # Grab a single line
                        unicode_line: str = accumulator[:index].decode("utf-8").strip()
                        if unicode_line:  # Skip empty lines
                            # We have a line with something in it.
                            # Decode and yield as a dictionary
                            result_dict = json.loads(unicode_line)
                            yield result_dict

                        # Remove the previous line from the accumulator
                        del accumulator[:index + len(separator)]

                        # Allow for case of multiple lines in one chunk
                        index = accumulator.find(separator)

                # If there is anything left in the accumulator, yield it
                if len(accumulator) > 0:
                    unicode_line: str = accumulator.decode("utf-8").strip()
                    if unicode_line:
                        result_dict = json.loads(unicode_line)
                        yield result_dict

        except Exception as exc:  # pylint: disable=broad-exception-caught
            if self.is_closed():
                # The read was interrupted by a deliberate close() from another
                # thread, not a real connectivity failure. Raise a dedicated error
                # so callers can tell cancellation apart from a lost connection.
                raise AgentSessionClosedError(
                    "HTTP agent session was closed during streaming_chat()") from exc
            raise ValueError(self.help_message(path)) from exc
        finally:
            # The request is over (normally, by error, or because close() dropped
            # the connection); stop tracking its response.
            with self._stream_lock:
                self._active_response = None

    def close(self):
        """
        Close this session by dropping any in-flight streaming connection.

        Marks the session closed and closes the currently-streaming response (if
        any), releasing its socket and unblocking the read in streaming_chat() on
        the client side. Safe to call from a different thread than the one
        iterating streaming_chat(), and safe to call more than once.

        Client-side scope: close() reliably drops the connection once response
        headers have arrived (i.e. once streaming has begun). A request still
        blocked on the very first header round-trip cannot be force-interrupted
        through the synchronous `requests` library from another thread; that
        window is bounded in practice because the neuro-san streaming service
        flushes response headers immediately, before doing the agent work, so the
        long-running wait is the post-header streaming read -- which close() does
        interrupt. (The async client has no such window: it aborts the underlying
        client session, cancelling even a pre-header request.)

        Server-side scope: close() releases the client connection; it does NOT
        directly cancel the server-side work. The neuro-san service ends the
        corresponding request only when it next detects the dropped connection --
        on its next result or heartbeat flush. That is prompt while results stream
        (or a keep-alive heartbeat is enabled), but a request producing no output
        with heartbeat and request-timeout disabled may keep running server-side
        until it does.
        """
        response: Optional[requests.Response] = None
        with self._stream_lock:
            self._closed = True
            response = self._active_response
            self._active_response = None
        if response is not None:
            with suppress(Exception):
                # Best-effort: the connection may already be torn down.
                response.close()
