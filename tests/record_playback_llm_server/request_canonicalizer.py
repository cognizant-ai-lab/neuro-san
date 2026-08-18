
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
See class comment for details.
"""
from __future__ import annotations

import hashlib
import json

from typing import Any
from typing import Dict
from typing import Tuple


class RequestCanonicalizer:
    """
    Turns an incoming HTTP request (method + upstream path + body) into a
    stable canonical string and a content hash used as the cassette key.

    The response of an LLM is non-deterministic, but the *request* is a
    deterministic function of the agent network plus its inputs. In a
    multi-turn agent flow each request embeds the previous responses
    (assistant messages, tool_call ids, tool results); as long as playback
    returns byte-identical recorded responses, every downstream request
    reconstructs identically -- so hashing the canonicalized request body is
    a stable key across an entire conversation.

    Canonicalization parses the JSON body and re-serializes it with sorted
    keys so that incidental key ordering does not change the hash. The
    `stream` flag is deliberately kept as part of the key: a streamed request
    and a one-shot request map to different recorded responses.
    """

    # Fields removed from the body before hashing. An immutable tuple so it
    # cannot be mutated at run time (which would silently change keying for
    # every caller in-process). Empty by default; extend this tuple in source
    # if a client is found to inject a per-run volatile value (a random request
    # id, a timestamp, etc.) into the request body.
    VOLATILE_BODY_KEYS: Tuple[str, ...] = ()

    @staticmethod
    def canonical_string(method: str, path: str, body_bytes: bytes) -> str:
        """
        :param method: HTTP method, e.g. "POST" or "GET".
        :param path: Upstream path the request targets, e.g. "/chat/completions".
        :param body_bytes: Raw request body bytes (maybe empty).
        :return: A canonical, deterministic string representation of the request.
        """
        body_repr: str = RequestCanonicalizer._canonical_body(body_bytes)
        return f"{method.upper()} {path}\n{body_repr}"

    @staticmethod
    def key(method: str, path: str, body_bytes: bytes) -> str:
        """
        :param method: HTTP method, e.g. "POST" or "GET".
        :param path: Upstream path the request targets, e.g. "/chat/completions".
        :param body_bytes: Raw request body bytes (may be empty).
        :return: A hex sha256 digest of the canonical string, used as cassette key.
        """
        canonical: str = RequestCanonicalizer.canonical_string(method, path, body_bytes)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    @staticmethod
    def _canonical_body(body_bytes: bytes) -> str:
        """
        Produce a deterministic representation of the request body. JSON bodies
        are parsed, stripped of volatile keys, and re-serialized with sorted
        keys. Non-JSON bodies fall back to their raw decoded text.
        """
        if not body_bytes:
            return ""
        try:
            parsed: Any = json.loads(body_bytes)
        except (json.JSONDecodeError, ValueError):
            return body_bytes.decode("utf-8", errors="replace")

        if isinstance(parsed, dict):
            for volatile_key in RequestCanonicalizer.VOLATILE_BODY_KEYS:
                parsed.pop(volatile_key, None)

        return json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def parsed_body(body_bytes: bytes) -> Dict[str, Any]:
        """
        Best-effort parse of a JSON object request body for inspection
        (e.g. detecting the `stream` flag). Returns an empty dict when the
        body is missing or not a JSON object.
        """
        if not body_bytes:
            return {}
        try:
            parsed: Any = json.loads(body_bytes)
        except (json.JSONDecodeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
