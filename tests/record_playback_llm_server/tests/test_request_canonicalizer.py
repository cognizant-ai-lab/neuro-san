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
Tests for RequestCanonicalizer key stability.
"""
import json

from typing import Any
from typing import Dict
from unittest import TestCase

from tests.record_playback_llm_server.request_canonicalizer import RequestCanonicalizer


class TestRequestCanonicalizer(TestCase):
    """
    Canonical-key stability guarantees the record/playback matching relies on.
    """

    PATH: str = "/v1/chat/completions"

    @staticmethod
    def _key(body: Dict[str, Any], method: str = "POST", path: str = PATH) -> str:
        """
        Computes the cassette key for a JSON body.

        :param body: The request body to serialize and hash
        :param method: The HTTP method of the request
        :param path: The upstream path of the request
        :return: The canonical cassette key
        """
        body_bytes: bytes = json.dumps(body).encode()
        return RequestCanonicalizer.key(method, path, body_bytes)

    def test_key_ignores_json_key_order(self) -> None:
        """
        Requests differing only in JSON key order hash to the same key.
        """
        body_a: Dict[str, Any] = {"model": "m", "stream": False, "messages": []}
        body_b: Dict[str, Any] = {"messages": [], "stream": False, "model": "m"}

        self.assertEqual(self._key(body_a), self._key(body_b))

    def test_stream_flag_changes_key(self) -> None:
        """
        A streamed request and a one-shot request map to different keys.
        """
        one: Dict[str, Any] = {"model": "m", "stream": False}
        streamed: Dict[str, Any] = {"model": "m", "stream": True}

        self.assertNotEqual(self._key(one), self._key(streamed))

    def test_path_and_method_participate(self) -> None:
        """
        Method and path are part of the key, not just the body.
        """
        body: bytes = b"{}"

        self.assertNotEqual(RequestCanonicalizer.key("POST", "/chat/completions", body),
                            RequestCanonicalizer.key("GET", "/chat/completions", body))

    def test_store_is_volatile_but_other_fields_are_not(self) -> None:
        """
        Requests that differ only by "store" hash identically, while a real request field
        still changes the key.

        neuro-san's openai class now sends store=false on every request; store only controls
        whether OpenAI keeps the response server-side and never changes the answer, so dropping
        it keeps cassettes recorded before that default matching the requests sent today.
        """
        base: Dict[str, Any] = {"model": "m", "stream": False, "messages": [{"role": "user", "content": "hi"}]}
        with_store_false: Dict[str, Any] = dict(base)
        with_store_false["store"] = False
        with_store_true: Dict[str, Any] = dict(base)
        with_store_true["store"] = True
        different_message: Dict[str, Any] = dict(base)
        different_message["messages"] = [{"role": "user", "content": "bye"}]

        self.assertIn("store", RequestCanonicalizer.VOLATILE_BODY_KEYS)
        self.assertEqual(self._key(base), self._key(with_store_false))
        self.assertEqual(self._key(base), self._key(with_store_true))
        self.assertNotEqual(self._key(base), self._key(different_message))
