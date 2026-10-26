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

from logging import Logger
from logging import getLogger
from time import perf_counter
from traceback import format_exc
from typing import Any
from typing import Dict
from typing import Optional

from neuro_san.client.streaming_input_processor import StreamingInputProcessor
from neuro_san.message.processors.basic_message_processor import BasicMessageProcessor
from neuro_san.session.http_service_agent_session import HttpServiceAgentSession

from tests.load_tests.traffic.agent_request_result import AgentRequestResult
from tests.load_tests.traffic.request_status_policy import RequestStatusPolicy
from tests.load_tests.traffic.request_timeout_error import RequestTimeoutError
from tests.load_tests.traffic.timed_streaming_chat import TimedStreamingChat

# Timeout for the initial TCP connection.
CONNECT_TIMEOUT_SECONDS: int = 30


class AgentRequestExecutor:
    """
    Sends one streaming_chat request in the calling thread.

    Instantiates ``HttpServiceAgentSession`` and ``StreamingInputProcessor``
    directly, costing ~1-2 MB per concurrent request.  Timing is done by
    ``TimedStreamingChat`` and the recorded status by ``RequestStatusPolicy``.
    """

    def __init__(self) -> None:
        """
        Set up the logger.
        """
        self.logger: Logger = getLogger(self.__class__.__name__)

    def execute_request(self, request_settings: Dict[str, Any], prompt: str) -> AgentRequestResult:
        """
        Send one streaming_chat request in-thread.

        Creates an ``HttpServiceAgentSession`` and a ``StreamingInputProcessor``,
        then calls ``process_once()`` to send the request and consume the
        streaming response.

        :param request_settings: Where and how to send the request: "host", "port", "agent",
                                 "timeout_seconds" (cap on the whole request, --request-timeout),
                                 "idle_timeout_seconds" (cap between streamed messages, --idle-timeout),
                                 "use_https" (default False) and "chat_filter_type" (default "MAXIMAL")
        :param prompt: User text to send
        :return: The AgentRequestResult; its processor is the
                 BasicMessageProcessor that saw the whole stream (answer,
                 structure, sly_data), for the caller's response checks,
                 and None when the request did not complete
        """
        start_seconds: float = perf_counter()
        timeout_seconds: float = request_settings.get("timeout_seconds")
        policy: RequestStatusPolicy = RequestStatusPolicy(timeout_seconds)
        session: HttpServiceAgentSession = AgentRequestExecutor._create_session(request_settings)

        # process_once() iterates session.streaming_chat internally, so the
        # timing wrapper is installed on the session.
        timed_chat: TimedStreamingChat = TimedStreamingChat(session.streaming_chat, start_seconds, timeout_seconds)
        session.streaming_chat = timed_chat.streaming_chat

        processor: StreamingInputProcessor = StreamingInputProcessor(
            default_input="DEFAULT",
            thinking_file=None,
            session=session,
            thinking_dir=None,
        )

        state: Dict[str, Any] = AgentRequestExecutor._initial_state(request_settings, prompt)

        error_text: str = ""
        try:
            state = processor.process_once(state)
        except RequestTimeoutError:
            # Raised by TimedStreamingChat at or past the cap; the elapsed
            # check below records it as TIMEOUT.
            pass
        # Broad by design: process_once() drives the third-party
        # HTTP/streaming stack, whose failure surface (connection,
        # decode, gRPC/transport errors) is not enumerable here.  This
        # is a per-request isolation boundary — any single request must
        # be recorded as FAILED/TIMEOUT without aborting the load test.
        except Exception:  # pylint: disable=broad-exception-caught
            # Include the full chained traceback so the root cause
            # (ReadTimeout, ConnectionError, HTTPError, ...) survives
            # the generic help text raised by the session client.
            error_text = format_exc()
            self.logger.debug("HTTP request failed:\n%s", error_text)

        elapsed_seconds: float = perf_counter() - start_seconds
        answer_text: str = state.get("last_chat_response") or ""
        status: str = policy.status_for(elapsed_seconds, answer_text, error_text)
        response: Dict[str, Any] = {}
        if policy.is_timed_out(elapsed_seconds):
            return AgentRequestResult(status, response)
        if error_text:
            response = {"response_text": error_text}
            return AgentRequestResult(status, response)

        response = AgentRequestExecutor._answer_response(processor, timed_chat, state, answer_text)
        return AgentRequestResult(status, response)

    @staticmethod
    def _initial_state(request_settings: Dict[str, Any], prompt: str) -> Dict[str, Any]:
        """
        Build the state dict that process_once() starts from.

        :param request_settings: The request settings described in execute_request()
        :param prompt: User text to send
        :return: The state, with the prompt as user_input and the chat filter type
                 from request_settings ("MAXIMAL" when not set)
        """
        chat_filter_type: str = request_settings.get("chat_filter_type", "MAXIMAL")
        state: Dict[str, Any] = {
            "last_chat_response": None,
            "num_input": 0,
            "user_input": prompt,
            "sly_data": None,
            "chat_filter": {
                "chat_filter_type": chat_filter_type,
            },
        }
        return state

    @staticmethod
    def _answer_response(processor: StreamingInputProcessor, timed_chat: TimedStreamingChat, state: Dict[str, Any],
                         answer_text: str) -> Dict[str, Any]:
        """
        Build the response of an answered request for AgentRequestResult.

        :param processor: The input processor that read the whole stream
        :param timed_chat: The stream wrapper that timed the first response
        :param state: The request state after process_once()
        :param answer_text: The agent's answer
        :return: A dictionary with "processor", "response_text", "time_to_first_response_seconds" and
            "token_accounting"
        """
        token_accounting: Dict[str, Any] = state.get("token_accounting") or {}
        message_processor: BasicMessageProcessor = processor.get_message_processor()
        time_to_first_response_seconds: float = timed_chat.get_time_to_first_response_seconds()
        response: Dict[str, Any] = {
            "processor": message_processor,
            "response_text": answer_text,
            "time_to_first_response_seconds": time_to_first_response_seconds,
            "token_accounting": token_accounting,
        }
        return response

    @staticmethod
    def _create_session(request_settings: Dict[str, Any]) -> HttpServiceAgentSession:
        """
        Create the HTTP session for one request.

        When "use_https" is True, a ``security_cfg`` is supplied so the session
        connects over HTTPS/TLS instead of plain HTTP.

        :param request_settings: The request settings described in execute_request()
        :return: The session, not yet connected
        """
        security_cfg: Optional[Dict[str, Any]] = None
        if request_settings.get("use_https", False):
            security_cfg = {}
        host: str = request_settings.get("host")
        port: int = request_settings.get("port")
        port_text: str = str(port)
        agent: str = request_settings.get("agent")
        idle_timeout_seconds: float = request_settings.get("idle_timeout_seconds")
        session: HttpServiceAgentSession = HttpServiceAgentSession(
            host=host,
            port=port_text,
            agent_name=agent,
            security_cfg=security_cfg,
            timeout_in_seconds=CONNECT_TIMEOUT_SECONDS,
            streaming_timeout_in_seconds=idle_timeout_seconds,
        )
        return session
