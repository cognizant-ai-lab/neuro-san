
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

import argparse
import unittest

from typing import List

from record_playback_llm_server.cors_policy import CorsPolicy
from record_playback_llm_server.proxy_state import ProxyState
from record_playback_llm_server.record_playback_llm_server import RecordPlaybackLlmServer


class TestRecordPlaybackLlmServer(unittest.TestCase):
    """
    How the command line becomes the policies the server runs with.
    """

    SITE: str = "http://alpha.localhost:8080"

    def parse(self, extra: List[str]) -> argparse.Namespace:
        """
        Parse a playback command line with the given extra flags.

        :param extra: The flags under test.
        :return: The parsed command line.
        """
        argv: List[str] = ["--mode", ProxyState.MODE_PLAYBACK]
        argv.extend(extra)
        args: argparse.Namespace = RecordPlaybackLlmServer.parse_args(argv)
        return args

    def test_no_flag_admits_no_browser_page(self):
        """The proxy stays as it was for a caller that is not a browser."""
        args: argparse.Namespace = self.parse([])
        policy: CorsPolicy = RecordPlaybackLlmServer.build_cors(args)
        self.assertFalse(policy.is_enabled())

    def test_allow_any_origin_admits_every_page(self):
        """One switch opens the proxy to every origin."""
        args: argparse.Namespace = self.parse(["--allow-any-origin"])
        policy: CorsPolicy = RecordPlaybackLlmServer.build_cors(args)
        self.assertTrue(policy.allow_any)
        self.assertTrue(policy.allows(self.SITE))
        self.assertTrue(policy.allows("http://anywhere.example.com"))

    def test_allow_origin_admits_only_what_it_names(self):
        """Naming an origin leaves every other origin out."""
        args: argparse.Namespace = self.parse(["--allow-origin", self.SITE])
        policy: CorsPolicy = RecordPlaybackLlmServer.build_cors(args)
        self.assertFalse(policy.allow_any)
        self.assertTrue(policy.allows(self.SITE))
        self.assertFalse(policy.allows("http://anywhere.example.com"))

    def test_the_flag_can_repeat(self):
        """Several origins are named one flag at a time."""
        args: argparse.Namespace = self.parse(
            ["--allow-origin", self.SITE, "--allow-origin", "http://beta.localhost:8080"])
        policy: CorsPolicy = RecordPlaybackLlmServer.build_cors(args)
        self.assertTrue(policy.allows(self.SITE))
        self.assertTrue(policy.allows("http://beta.localhost:8080"))

    def test_both_flags_together_admit_every_page(self):
        """The wider flag wins, so a named origin does not narrow it."""
        args: argparse.Namespace = self.parse(["--allow-origin", self.SITE, "--allow-any-origin"])
        policy: CorsPolicy = RecordPlaybackLlmServer.build_cors(args)
        self.assertTrue(policy.allow_any)
        self.assertTrue(policy.allows("http://anywhere.example.com"))

    def test_one_command_line_does_not_reach_the_next(self):
        """A repeatable flag must not keep its values for a later parse."""
        self.parse(["--allow-origin", self.SITE])
        args: argparse.Namespace = self.parse([])
        policy: CorsPolicy = RecordPlaybackLlmServer.build_cors(args)
        self.assertFalse(policy.is_enabled())


if __name__ == "__main__":
    unittest.main()
