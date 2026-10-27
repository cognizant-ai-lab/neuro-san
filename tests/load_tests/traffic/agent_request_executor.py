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
from traceback import format_exception
from traceback import format_exception_only
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from leaf_common.logging.sensitive_logger import SensitiveLogger
# requests raises urllib3's ReadTimeoutError as the cause of its own error when no data comes within the
# read timeout, while waiting for the response headers and while streaming the response.
from urllib3.exceptions import ReadTimeoutError

from neuro_san.client.streaming_input_processor import StreamingInputProcessor
from neuro_san.message.processors.basic_message_processor import BasicMessageProcessor
from neuro_san.session.http_service_agent_session import HttpServiceAgentSession

from tests.load_tests.traffic.agent_request_result import AgentRequestResult
from tests.load_tests.traffic.output_parser import OutputParser
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

        raised_error: Optional[Exception] = None
        try:
            state = processor.process_once(state)
        except RequestTimeoutError:
            # Raised by TimedStreamingChat at or past the cap; the elapsed
            # check in _answer_result() records it as TIMEOUT.
            pass
        # Broad by design: process_once() drives the third-party
        # HTTP/streaming stack, whose failure surface (connection,
        # decode, gRPC/transport errors) is not enumerable here.  This
        # is a per-request isolation boundary — any single request must
        # be recorded as FAILED/TIMEOUT without aborting the load test.
        except Exception as error:  # pylint: disable=broad-exception-caught
            raised_error = error

        elapsed_seconds: float = perf_counter() - start_seconds
        if raised_error is not None:
            return self._error_result(policy, elapsed_seconds, raised_error)
        return AgentRequestExecutor._answer_result(policy, elapsed_seconds, processor, timed_chat, state)

    def _error_result(self, policy: RequestStatusPolicy, elapsed_seconds: float,
                      error: Exception) -> AgentRequestResult:
        """
        Build the result of a request that raised.

        :param policy: Decides the status from the elapsed time and the error
        :param elapsed_seconds: Seconds the request took
        :param error: The exception the request raised
        :return: The AgentRequestResult: TIMEOUT with no response past the cap, TIMEOUT with the reason
            after a read timeout, else FAILED with the traceback as response text and the reason
        """
        # Include the full chained traceback so the root cause
        # (ReadTimeout, ConnectionError, HTTPError, ...) survives
        # the generic help text raised by the session client.
        error_lines: List[str] = format_exception(error)
        error_text: str = "".join(error_lines)
        # The traceback holds the error message, so it goes through a SensitiveLogger; when LEAF_LOG_SENSITIVE is
        # off, only the error type is logged.
        sensitive_logger: SensitiveLogger = SensitiveLogger(self.logger)
        sensitive_logger.debug("HTTP request failed:\n%s", error_text)
        if not sensitive_logger.should_log():
            self.logger.debug("HTTP request failed: %s", type(error).__name__)
        failure_reason: str = AgentRequestExecutor._error_reason(error)
        read_timed_out: bool = AgentRequestExecutor._is_read_timeout(error)
        status: str = policy.status_for(elapsed_seconds, "", error_text, read_timed_out)
        response: Dict[str, Any] = {}
        if policy.is_timed_out(elapsed_seconds):
            return AgentRequestResult(status, response)
        if read_timed_out:
            # RequestRecorder saves a traceback only for FAILED, so a read timeout keeps only the reason.
            response = {"failure_reason": failure_reason}
            return AgentRequestResult(status, response)
        response = {
            "response_text": error_text,
            "failure_reason": failure_reason,
        }
        return AgentRequestResult(status, response)

    @staticmethod
    def _answer_result(policy: RequestStatusPolicy, elapsed_seconds: float, processor: StreamingInputProcessor,
                       timed_chat: TimedStreamingChat, state: Dict[str, Any]) -> AgentRequestResult:
        """
        Build the result of a request that did not raise.

        :param policy: Decides the status from the elapsed time and the answer
        :param elapsed_seconds: Seconds the request took
        :param processor: The input processor that read the stream
        :param timed_chat: The stream wrapper that timed the first response
        :param state: The request state after process_once()
        :return: The AgentRequestResult: TIMEOUT with no response past the cap, else FAILED or CREATED
            with the answer response
        """
        answer_text: str = state.get("last_chat_response") or ""
        status: str = policy.status_for(elapsed_seconds, answer_text)
        response: Dict[str, Any] = {}
        if policy.is_timed_out(elapsed_seconds):
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
        timeout_seconds: float = request_settings.get("timeout_seconds")
        # TimedStreamingChat checks --request-timeout only when a message arrives, so a silent stream
        # is stopped by this read timeout: never wait longer than the cap on the whole request.
        read_timeout_seconds: float = min(idle_timeout_seconds, timeout_seconds)
        session: HttpServiceAgentSession = HttpServiceAgentSession(
            host=host,
            port=port_text,
            agent_name=agent,
            security_cfg=security_cfg,
            timeout_in_seconds=CONNECT_TIMEOUT_SECONDS,
            streaming_timeout_in_seconds=read_timeout_seconds,
        )
        return session

    @staticmethod
    def _error_reason(error: Exception) -> str:
        """
        Name the error a request raised in one line.

        The session client raises a ValueError with its connectivity help text from the real
        error, so the reason names that cause instead of the last line of the help text.

        :param error: The exception the request raised
        :return: The last line of "<type>: <message>" of the error's cause, or of the error itself when it has none
        """
        reported: BaseException = error
        if error.__cause__ is not None:
            reported = error.__cause__
        error_lines: List[str] = format_exception_only(reported)
        error_text: str = "".join(error_lines)
        return OutputParser.last_stderr_line(error_text)

    @staticmethod
    def _is_read_timeout(error: Exception) -> bool:
        """
        Tell whether a request raised because no data came within the session's read timeout.

        :param error: The exception the request raised
        :return: True when a urllib3 ReadTimeoutError is in the error's cause or context chain
        """
        chained: Optional[BaseException] = error
        seen_errors: List[BaseException] = []
        # Walk down the chain of causes, stopping at its end or at a loop.
        while chained is not None and chained not in seen_errors:
            if isinstance(chained, ReadTimeoutError):
                return True
            seen_errors.append(chained)
            next_error: Optional[BaseException] = chained.__cause__
            if next_error is None:
                next_error = chained.__context__
            chained = next_error
        return False
