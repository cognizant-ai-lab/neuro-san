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

"""In-thread HTTP client for load testing without subprocess overhead.

Instead of spawning a separate ``python -m neuro_san.client.agent_cli``
process per request (~96 MB each), this module instantiates
``HttpServiceAgentSession`` and ``StreamingInputProcessor`` directly
in the calling thread.  Memory cost drops from ~96 MB per concurrent
request to ~1-2 MB per thread.
"""

import logging
import time
from typing import Any
from typing import Dict
from typing import List
from typing import Tuple

from neuro_san.client.streaming_input_processor import (
    StreamingInputProcessor,
)
from neuro_san.session.http_service_agent_session import (
    HttpServiceAgentSession,
)

from tests.load_tests.config import STATUS_CREATED
from tests.load_tests.config import STATUS_FAILED
from tests.load_tests.config import STATUS_TIMEOUT

logger = logging.getLogger(__name__)

# Timeout for the initial TCP connection (seconds).
_CONNECT_TIMEOUT = 30


class HttpClient:
    """Runs agent_cli logic in-thread via HttpServiceAgentSession."""

    @staticmethod
    def execute_request(
            host, port, agent, prompt, *,
            timeout, idle_timeout, use_https=False,
    ) -> Tuple[str, Dict[str, str], str, float, Dict]:
        """Send one streaming_chat request using the agent_cli
        client stack in-thread.

        Creates an ``HttpServiceAgentSession`` and a
        ``StreamingInputProcessor`` (the same objects that
        ``agent_cli`` uses), then calls ``process_once()``
        to send the request, consume the streaming response,
        and extract sly_data fields.  When ``use_https`` is True,
        a ``security_cfg`` is supplied so the session connects
        over HTTPS/TLS instead of plain HTTP.

        Returns (status, parsed_fields, response_text, ttft,
        token_accounting).
        """
        start = time.time()

        security_cfg: Dict[str, Any] = {} if use_https else None
        session = HttpServiceAgentSession(
            host=host,
            port=str(port),
            agent_name=agent,
            security_cfg=security_cfg,
            timeout_in_seconds=_CONNECT_TIMEOUT,
            streaming_timeout_in_seconds=idle_timeout,
        )

        # Time-to-first-response: wrap the session's streaming_chat so
        # the first streamed chat message is timestamped, matching the
        # subprocess mode's time-to-first-stdout metric. process_once()
        # iterates this generator internally.
        first_response: List[float] = []
        original_streaming_chat = session.streaming_chat

        def timed_streaming_chat(request_dict):
            # Nested to close over original_streaming_chat, start, and
            # first_response so the first streamed message is timed
            # without threading that state through process_once().
            for chat_response in original_streaming_chat(request_dict):
                if not first_response:
                    first_response.append(time.time() - start)
                yield chat_response

        session.streaming_chat = timed_streaming_chat

        processor = StreamingInputProcessor(
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
                "chat_filter_type": "MAXIMAL",
            },
        }

        try:
            state = processor.process_once(state)
        # Broad by design: process_once() drives the third-party
        # HTTP/streaming stack, whose failure surface (connection,
        # decode, gRPC/transport errors) is not enumerable here.  This
        # is a per-request isolation boundary — any single request must
        # be recorded as FAILED/TIMEOUT without aborting the load test.
        except Exception as exc:  # pylint: disable=broad-exception-caught
            elapsed = time.time() - start
            if elapsed >= timeout:
                return (STATUS_TIMEOUT, {}, "", 0.0, {})
            logger.debug("HTTP request failed: %s", exc)
            return (STATUS_FAILED, {}, str(exc), 0.0, {})

        elapsed = time.time() - start
        if elapsed >= timeout:
            return (STATUS_TIMEOUT, {}, "", 0.0, {})

        answer_text = state.get("last_chat_response") or ""
        returned_sly_data = state.get(
            "returned_sly_data",
        ) or {}
        token_accounting = state.get(
            "token_accounting",
        ) or {}

        parsed_fields: Dict[str, str] = {}
        HttpClient._extract_string_fields(
            returned_sly_data, parsed_fields,
        )

        status = (
            STATUS_CREATED if answer_text
            else STATUS_FAILED
        )
        ttft = first_response[0] if first_response else 0.0
        return (
            status, parsed_fields, answer_text,
            ttft, token_accounting,
        )

    @staticmethod
    def _extract_string_fields(
            obj, parsed_fields,
    ):
        """Recursively extract string-valued fields.

        The subprocess mode prints sly_data as JSON and then
        regex-searches the entire stdout.  Fields like
        ``reservation_id`` may be nested inside lists (e.g.
        ``sly_data["agent_reservations"][0]["reservation_id"]``).
        A flat top-level scan misses them, so we recurse.
        """
        if isinstance(obj, dict):
            for key, value in obj.items():
                if isinstance(value, str):
                    parsed_fields.setdefault(key, value)
                elif isinstance(value, (dict, list)):
                    HttpClient._extract_string_fields(
                        value, parsed_fields,
                    )
        elif isinstance(obj, list):
            for item in obj:
                if isinstance(item, (dict, list)):
                    HttpClient._extract_string_fields(
                        item, parsed_fields,
                    )
