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

import logging
import time
import traceback
from typing import Any
from typing import Dict
from typing import Optional

from neuro_san.client.streaming_input_processor import StreamingInputProcessor
from neuro_san.session.http_service_agent_session import HttpServiceAgentSession

from tests.load_tests.traffic.agent_request_result import AgentRequestResult
from tests.load_tests.traffic.request_status_policy import RequestStatusPolicy
from tests.load_tests.traffic.request_timeout_error import RequestTimeoutError
from tests.load_tests.traffic.timed_streaming_chat import TimedStreamingChat

logger: logging.Logger = logging.getLogger(__name__)

# Timeout for the initial TCP connection.
CONNECT_TIMEOUT_SECONDS: int = 30


class AgentRequestExecutor:
    """
    Sends one streaming_chat request in the calling thread.

    Instantiates ``HttpServiceAgentSession`` and ``StreamingInputProcessor``
    directly, costing ~1-2 MB per concurrent request.  Timing is done by
    ``TimedStreamingChat`` and the recorded status by ``RequestStatusPolicy``.
    """

    @staticmethod
    def execute_request(host: str, port: int, agent: str, prompt: str, timeout: float, idle_timeout: float,
                        use_https: bool = False, chat_filter_type: str = "MAXIMAL") -> AgentRequestResult:
        """
        Send one streaming_chat request in-thread.

        Creates an ``HttpServiceAgentSession`` and a ``StreamingInputProcessor``,
        then calls ``process_once()`` to send the request and consume the
        streaming response.  When ``use_https`` is True, a ``security_cfg`` is
        supplied so the session connects over HTTPS/TLS instead of plain HTTP.

        :param host: Server host name
        :param port: Server port
        :param agent: Name of the agent network to call
        :param prompt: User text to send
        :param timeout: Cap in seconds on the whole request (--request-timeout)
        :param idle_timeout: Cap in seconds between streamed messages (--idle-timeout)
        :param use_https: When True connect over HTTPS/TLS
        :param chat_filter_type: chat_filter_type to send with the request
        :return: The AgentRequestResult; its processor is the
                 BasicMessageProcessor that saw the whole stream (answer,
                 structure, sly_data), for the caller's response checks,
                 and None when the request did not complete
        """
        # The argument list tracks the streaming_chat request surface.
        # pylint: disable=too-many-arguments,too-many-positional-arguments,too-many-locals
        start_seconds: float = time.perf_counter()
        policy: RequestStatusPolicy = RequestStatusPolicy(timeout)

        security_cfg: Optional[Dict[str, Any]] = {} if use_https else None
        session: HttpServiceAgentSession = HttpServiceAgentSession(
            host=host,
            port=str(port),
            agent_name=agent,
            security_cfg=security_cfg,
            timeout_in_seconds=CONNECT_TIMEOUT_SECONDS,
            streaming_timeout_in_seconds=idle_timeout,
        )

        # process_once() iterates session.streaming_chat internally, so the
        # timing wrapper is installed on the session.
        timed_chat: TimedStreamingChat = TimedStreamingChat(session.streaming_chat, start_seconds, timeout)
        session.streaming_chat = timed_chat.streaming_chat

        processor: StreamingInputProcessor = StreamingInputProcessor(
            default_input="DEFAULT",
            thinking_file=None,
            session=session,
            thinking_dir=None,
        )

        state: Dict[str, Any] = {
            "last_chat_response": None,
            "num_input": 0,
            "user_input": prompt,
            "sly_data": None,
            "chat_filter": {
                "chat_filter_type": chat_filter_type,
            },
        }

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
            error_text = traceback.format_exc()
            logger.debug("HTTP request failed:\n%s", error_text)

        elapsed_seconds: float = time.perf_counter() - start_seconds
        answer_text: str = state.get("last_chat_response") or ""
        status: str = policy.status_for(elapsed_seconds, answer_text, error_text)
        if policy.is_timed_out(elapsed_seconds):
            return AgentRequestResult(status, None, "", 0.0, {})
        if error_text:
            return AgentRequestResult(status, None, error_text, 0.0, {})

        token_accounting: Dict[str, Any] = state.get("token_accounting") or {}
        return AgentRequestResult(
            status, processor.get_message_processor(), answer_text,
            timed_chat.get_time_to_first_response(), token_accounting,
        )
