
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

from __future__ import annotations

from typing import Dict

import unittest

from tests.record_playback_llm_server.cors_policy import CorsPolicy


class TestCorsPolicy(unittest.TestCase):
    """
    Which origins the policy admits, and the headers it builds for them.
    """

    SITE: str = "http://alpha.localhost:8080"

    def test_a_policy_with_no_origins_admits_nothing(self):
        """An operator who names no origin leaves the proxy as it was."""
        policy = CorsPolicy()
        self.assertFalse(policy.is_enabled())
        self.assertFalse(policy.allows(self.SITE))
        self.assertEqual({}, policy.response_headers(self.SITE))
        self.assertEqual({}, policy.preflight_headers(self.SITE))

    def test_a_named_origin_is_admitted_and_others_are_not(self):
        """Only the origins the operator named get permission headers."""
        policy = CorsPolicy([self.SITE])
        self.assertTrue(policy.allows(self.SITE))
        self.assertFalse(policy.allows("http://beta.localhost:8080"))
        self.assertEqual({}, policy.response_headers("http://beta.localhost:8080"))

    def test_a_named_origin_is_echoed_with_vary(self):
        """An answer that differs by origin tells caches so."""
        policy = CorsPolicy([self.SITE])
        headers: Dict[str, str] = policy.response_headers(self.SITE)
        self.assertEqual(self.SITE, headers.get("Access-Control-Allow-Origin"))
        self.assertEqual("Origin", headers.get("Vary"))

    def test_the_wildcard_admits_every_origin_without_vary(self):
        """One answer suits every origin, so there is nothing to vary on."""
        policy = CorsPolicy([CorsPolicy.WILDCARD])
        headers: Dict[str, str] = policy.response_headers("http://anywhere.example.com")
        self.assertEqual(CorsPolicy.WILDCARD, headers.get("Access-Control-Allow-Origin"))
        self.assertIsNone(headers.get("Vary"))

    def test_an_origin_is_matched_whatever_its_case_or_trailing_slash(self):
        """What an operator types and what a browser sends still meet."""
        policy = CorsPolicy(["HTTP://Alpha.Localhost:8080/"])
        self.assertTrue(policy.allows(self.SITE))

    def test_a_caller_with_no_origin_header_is_not_admitted(self):
        """A neuro-san process sends no Origin and needs no permission."""
        policy = CorsPolicy([CorsPolicy.WILDCARD])
        self.assertFalse(policy.allows(""))
        self.assertEqual({}, policy.response_headers(""))

    def test_a_preflight_answer_names_the_methods_and_the_headers(self):
        """The browser learns what the real call is allowed to be."""
        policy = CorsPolicy([self.SITE])
        headers: Dict[str, str] = policy.preflight_headers(self.SITE, "content-type, authorization")
        self.assertEqual("content-type, authorization", headers.get("Access-Control-Allow-Headers"))
        self.assertIn("POST", headers.get("Access-Control-Allow-Methods"))
        self.assertIn("OPTIONS", headers.get("Access-Control-Allow-Methods"))
        self.assertEqual(str(CorsPolicy.PREFLIGHT_MAX_AGE_SECONDS), headers.get("Access-Control-Max-Age"))

    def test_a_preflight_that_asks_for_nothing_gets_the_usual_headers(self):
        """A browser that lists no header still learns the common ones."""
        policy = CorsPolicy([self.SITE])
        headers: Dict[str, str] = policy.preflight_headers(self.SITE)
        self.assertEqual(", ".join(CorsPolicy.DEFAULT_ALLOWED_HEADERS),
                         headers.get("Access-Control-Allow-Headers"))

    def test_flag_values_are_split_on_commas(self):
        """One --allow-origin can carry a list, and the flag can repeat."""
        policy = CorsPolicy.from_values([f"{self.SITE}, http://beta.localhost:8080", "http://gamma.localhost"])
        self.assertTrue(policy.allows(self.SITE))
        self.assertTrue(policy.allows("http://beta.localhost:8080"))
        self.assertTrue(policy.allows("http://gamma.localhost"))

    def test_an_empty_flag_value_admits_nothing(self):
        """A flag given with nothing in it must not open the proxy."""
        policy = CorsPolicy.from_values(["", "  ", None])
        self.assertFalse(policy.is_enabled())

    def test_the_wildcard_among_named_origins_wins(self):
        """A list that holds '*' admits every origin."""
        policy = CorsPolicy.from_values([f"{self.SITE},*"])
        self.assertTrue(policy.allow_any)
        self.assertTrue(policy.allows("http://anywhere.example.com"))


if __name__ == "__main__":
    unittest.main()
