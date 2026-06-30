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

"""Direct HTTP client for load testing without subprocess overhead.

Instead of spawning a separate ``python -m neuro_san.client.agent_cli``
process per request (~96 MB each), this module makes HTTP POST calls
directly from the calling thread.  Memory cost drops from ~96 MB per
concurrent request to ~1-2 MB per thread, allowing a single client
machine to drive 1000+ concurrent requests.
"""

import json
import logging
import time
from typing import Any
from typing import Dict
from typing import Optional
from typing import Tuple

import requests

from tests.load_tests.config import STATUS_CREATED
from tests.load_tests.config import STATUS_FAILED
from tests.load_tests.config import STATUS_TIMEOUT

logger = logging.getLogger(__name__)

# Timeout for the initial TCP connection (seconds).
_CONNECT_TIMEOUT = 30


class HttpClient:
    """Sends streaming_chat requests over HTTP without subprocesses."""

    @staticmethod
    def execute_request(
            host, port, agent, prompt, *,
            timeout, idle_timeout,
    ) -> Tuple[str, Dict[str, str], str, float]:
        """Send one streaming_chat request and consume the response.

        Returns (status, parsed_fields, response_text, ttft).
          * status: STATUS_CREATED | STATUS_FAILED | STATUS_TIMEOUT
          * parsed_fields: dict of field_name -> value extracted
            from sly_data (e.g. reservation_id, agent_network_name)
          * response_text: concatenated answer text from the stream
          * ttft: time-to-first-token in seconds (0.0 if none)
        """
        url = (
            f"http://{host}:{port}"
            f"/api/v1/{agent}/streaming_chat"
        )
        body: Dict[str, Any] = {
            "user_message": {
                "type": "HUMAN",
                "text": prompt,
            }
        }

        start = time.time()
        ttft = 0.0
        answer_text = ""
        sly_data: Dict[str, Any] = {}

        try:
            with requests.post(
                url,
                json=body,
                stream=True,
                timeout=(_CONNECT_TIMEOUT, idle_timeout),
            ) as resp:
                resp.raise_for_status()
                answer_text, sly_data, ttft = (
                    HttpClient._consume_stream(
                        resp, start, timeout,
                    )
                )
        except requests.exceptions.Timeout:
            return (STATUS_TIMEOUT, {}, "", 0.0)
        except requests.exceptions.ConnectionError as exc:
            logger.debug("Connection error: %s", exc)
            return (STATUS_FAILED, {}, "", 0.0)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            logger.debug("HTTP request failed: %s", exc)
            return (STATUS_FAILED, {}, str(exc), 0.0)

        parsed_fields: Dict[str, str] = {}
        if sly_data:
            for key, value in sly_data.items():
                if isinstance(value, str):
                    parsed_fields[key] = value

        status = (
            STATUS_CREATED if answer_text
            else STATUS_FAILED
        )
        return (status, parsed_fields, answer_text, ttft)

    @staticmethod
    def _consume_stream(
            resp, start, timeout,
    ) -> Tuple[str, Dict[str, Any], float]:
        """Read a newline-delimited JSON stream.

        Returns (answer_text, sly_data, ttft).
        """
        separator = b"\n"
        max_chunk = 64 * 1024
        ttft = 0.0
        answer_text = ""
        sly_data: Dict[str, Any] = {}
        accumulator = bytearray()

        for data in resp.iter_content(chunk_size=max_chunk):
            if time.time() - start > timeout:
                return (answer_text, sly_data, ttft)

            accumulator.extend(data)
            index = accumulator.find(separator)
            while index >= 0:
                line = accumulator[:index].decode(
                    "utf-8", errors="replace",
                ).strip()
                del accumulator[:index + len(separator)]
                if line:
                    if not ttft:
                        ttft = time.time() - start
                    text, sly = HttpClient._process_line(
                        line, answer_text, sly_data,
                    )
                    if text is not None:
                        answer_text = text
                    if sly is not None:
                        sly_data = sly
                index = accumulator.find(separator)

        if accumulator:
            line = accumulator.decode(
                "utf-8", errors="replace",
            ).strip()
            if line:
                text, sly = HttpClient._process_line(
                    line, answer_text, sly_data,
                )
                if text is not None:
                    answer_text = text
                if sly is not None:
                    sly_data = sly

        return (answer_text, sly_data, ttft)

    @staticmethod
    def _process_line(
            line, current_answer, current_sly,
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        """Parse one JSON line and extract answer/sly_data.

        Returns (new_answer_or_None, new_sly_or_None).
        """
        try:
            result_dict = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            return (None, None)

        response = result_dict.get("response", {})
        if not isinstance(response, dict):
            return (None, None)

        new_answer = None
        new_sly = None

        text = response.get("text")
        if text:
            new_answer = text

        sly = response.get("sly_data")
        if sly and isinstance(sly, dict):
            new_sly = sly

        return (new_answer, new_sly)
