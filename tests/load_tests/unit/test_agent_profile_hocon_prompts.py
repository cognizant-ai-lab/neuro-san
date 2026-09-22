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

import glob
import os
import tempfile
from typing import List
from unittest import TestCase

from neuro_san import TOP_LEVEL_DIR
from tests.load_tests.config import DEFAULT_FIXTURES_HOCON_DIR
from tests.load_tests.prompts.agent_profile import AgentProfile

# Real fixtures, not mocks: tests/fixtures/load_tests/hello_world/*.hocon
PROJECT_ROOT: str = TOP_LEVEL_DIR.get_file_in_basis("..")
HELLO_WORLD_HOCONS: List[str] = sorted(glob.glob(TOP_LEVEL_DIR.get_file_in_basis(
    os.path.join("..", DEFAULT_FIXTURES_HOCON_DIR, "hello_world", "*.hocon"),
)))


class TestAgentProfileHoconPrompts(TestCase):
    """
    Unit tests for AgentProfile.load(..., hocon_files=...).

    Prompts must come from the hocon files; every other setting must
    be carried over unchanged from the JSON profile.
    """

    @staticmethod
    def _load(agent: str, hocon_files: List[str]) -> AgentProfile:
        """Load via the real JSON profile lookup plus the given hocons."""
        return AgentProfile.load(
            agent, project_root=PROJECT_ROOT, hocon_files=hocon_files,
        )

    @staticmethod
    def _write_hocon(folder: str, name: str, agent: str, texts: List[str]) -> str:
        """Write a minimal test-case hocon and return its path."""
        path: str = os.path.join(folder, name)
        interactions: str = ", ".join(f'{{ "text": "{t}" }}' for t in texts)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(
                f'{{ "agent": "{agent}", "interactions": [{interactions}] }}'
            )
        return path

    def test_prompts_come_from_hocon_files(self) -> None:
        """Each fixture's interactions[].text becomes a prompt."""
        profile: AgentProfile = self._load("hello_world", HELLO_WORLD_HOCONS)
        # One interaction per fixture, same prompts as the JSON profile
        self.assertEqual(len(profile.prompts), len(HELLO_WORLD_HOCONS))
        self.assertIn("Hello, how are you today?", profile.prompts)

    def test_non_prompt_settings_come_from_json(self) -> None:
        """Pass/fail settings are carried over from the JSON profile."""
        profile: AgentProfile = self._load("hello_world", HELLO_WORLD_HOCONS)
        self.assertEqual(profile.estimated_tokens_per_request, 1000)
        self.assertEqual(profile.success_fields, [])
        self.assertIn("No fully-specified LLM found", profile.failure_patterns)

    def test_prefixed_agent_accepts_base_name_in_hocon(self) -> None:
        """--agent basic/hello_world matches hocons whose agent is hello_world."""
        profile: AgentProfile = self._load("basic/hello_world", HELLO_WORLD_HOCONS)
        self.assertEqual(profile.agent_name, "basic/hello_world")
        self.assertEqual(len(profile.prompts), len(HELLO_WORLD_HOCONS))

    def test_multiple_interactions_in_one_file_all_used(self) -> None:
        """A hocon with several interactions yields several prompts."""
        with tempfile.TemporaryDirectory() as tmp:
            path: str = self._write_hocon(
                tmp, "multi.hocon", "hello_world", ["first", "second"],
            )
            profile: AgentProfile = self._load("hello_world", [path])
        self.assertEqual(profile.prompts, ["first", "second"])

    def test_agent_mismatch_exits_1(self) -> None:
        """A hocon for a different agent aborts the run."""
        with tempfile.TemporaryDirectory() as tmp:
            path: str = self._write_hocon(
                tmp, "other.hocon", "music_nerd", ["hi"],
            )
            with self.assertRaises(SystemExit) as ctx:
                self._load("hello_world", [path])
        self.assertEqual(ctx.exception.code, 1)

    def test_no_text_anywhere_exits_1(self) -> None:
        """No prompts at all aborts the run."""
        with tempfile.TemporaryDirectory() as tmp:
            path: str = self._write_hocon(tmp, "empty.hocon", "hello_world", [])
            with self.assertRaises(SystemExit) as ctx:
                self._load("hello_world", [path])
        self.assertEqual(ctx.exception.code, 1)
