
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
from unittest import TestCase

from tests.load_tests.prompts.agent_profile import AgentProfile


class TestAgentProfilePrompt(TestCase):
    """
    Unit tests for AgentProfile.get_prompt().

    The per-request suffix is what keeps a run from measuring cache
    hits, so a wrong answer here silently changes what is measured.
    """

    def setUp(self):
        """Build a profile with a two-prompt pool."""
        self.profile = AgentProfile(
            "music_nerd", {"prompts": ["first", "second"]},
        )

    def test_varied_mode_appends_request_id(self):
        """Default mode makes every prompt unique."""
        self.assertEqual(
            self.profile.get_prompt(0), "first (request 0)",
        )
        self.assertEqual(
            self.profile.get_prompt(3), "second (request 3)",
        )

    def test_allow_caching_keeps_pool_prompt_verbatim(self):
        """Cacheable mode still cycles the pool, without a suffix."""
        self.assertEqual(
            self.profile.get_prompt(0, allow_caching=True), "first",
        )
        self.assertEqual(
            self.profile.get_prompt(3, allow_caching=True), "second",
        )

    def test_same_prompt_wins_over_allow_caching(self):
        """same_prompt already repeats prompt zero verbatim."""
        self.assertEqual(
            self.profile.get_prompt(
                3, same_prompt=True, allow_caching=True,
            ),
            "first",
        )

    def test_empty_prompt_pool_aborts(self):
        """A profile with no prompts is a hard error."""
        empty = AgentProfile("music_nerd", {"prompts": []})
        with self.assertRaises(SystemExit):
            empty.get_prompt(0)
