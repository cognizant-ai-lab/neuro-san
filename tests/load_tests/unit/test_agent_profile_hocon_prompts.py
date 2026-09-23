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
import json
import os
import tempfile
from typing import Any
from typing import Dict
from typing import List
from unittest import TestCase

from neuro_san import TOP_LEVEL_DIR
from tests.load_tests.config import DEFAULT_FIXTURES_HOCON_DIR
from tests.load_tests.prompts.agent_profile import AgentProfile

# Real fixtures, not mocks: tests/fixtures/load_tests/<agent>/*.hocon
PROJECT_ROOT: str = TOP_LEVEL_DIR.get_file_in_basis("..")


class TestAgentProfileHoconPrompts(TestCase):
    """
    Unit tests for AgentProfile.load(..., hocon_files=...).

    With hocon files the whole profile (prompts, success_fields,
    failure_patterns, estimated_tokens_per_request) comes from them;
    the JSON profile is not read.
    """

    @staticmethod
    def _fixture_hocons(agent: str) -> List[str]:
        """Sorted hocon paths under the default fixtures dir for one agent."""
        return sorted(glob.glob(TOP_LEVEL_DIR.get_file_in_basis(
            os.path.join("..", DEFAULT_FIXTURES_HOCON_DIR, agent, "*.hocon"),
        )))

    @classmethod
    def _load_fixtures(cls, agent: str) -> AgentProfile:
        """Load the profile from the checked-in fixtures of one agent."""
        return cls._load(agent, cls._fixture_hocons(agent))

    @staticmethod
    def _load(agent: str, hocon_files: List[str]) -> AgentProfile:
        """Load the profile from the given hocons."""
        return AgentProfile.load(
            agent, project_root=PROJECT_ROOT, hocon_files=hocon_files,
        )

    @staticmethod
    def _write_hocon(folder: str, name: str, agent: str, texts: List[str],
                     **extra: Any) -> str:
        """Write a minimal test-case hocon (JSON is valid hocon) and return its path."""
        path: str = os.path.join(folder, name)
        test_case: Dict[str, Any] = {
            "agent": agent,
            "interactions": [{"text": text} for text in texts],
            **extra,
        }
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(test_case, fh)
        return path

    def test_prompts_come_from_hocon_files(self) -> None:
        """Each fixture's interactions[].text becomes a prompt."""
        profile: AgentProfile = self._load_fixtures("hello_world")
        # One interaction per fixture
        self.assertEqual(len(profile.prompts), len(self._fixture_hocons("hello_world")))
        self.assertIn("Hello, how are you today?", profile.prompts)

    def test_agent_settings_come_from_hocons(self) -> None:
        """failure_patterns are read from the hocons, not the JSON."""
        profile: AgentProfile = self._load_fixtures("hello_world")
        self.assertIsNone(profile.estimated_tokens_per_request)
        self.assertEqual(profile.success_fields, [])
        self.assertIn("No fully-specified LLM found", profile.failure_patterns)
        # Same pattern in every file -> listed once
        self.assertEqual(len(profile.failure_patterns), 2)

    def test_success_fields_come_from_response_sly_data_keys(self) -> None:
        """Each response.sly_data key becomes a required success field."""
        profile: AgentProfile = self._load_fixtures("agent_network_designer")
        self.assertEqual(len(profile.prompts), len(self._fixture_hocons("agent_network_designer")))
        self.assertEqual(profile.success_fields, ["reservation_id", "agent_network_name"])

    def test_json_profile_not_needed_with_hocons(self) -> None:
        """An agent with no JSON profile loads fine from hocons alone."""
        with tempfile.TemporaryDirectory() as tmp:
            path: str = self._write_hocon(
                tmp, "only.hocon", "no_such_agent", ["hi"],
                failure_patterns=["oops"], estimated_tokens_per_request=42,
            )
            profile: AgentProfile = self._load("no_such_agent", [path])
        self.assertEqual(profile.prompts, ["hi"])
        self.assertEqual(profile.failure_patterns, ["oops"])
        self.assertEqual(profile.success_fields, [])
        self.assertEqual(profile.estimated_tokens_per_request, 42)

    def test_sly_data_list_exits_1(self) -> None:
        """response.sly_data must be a field -> check map, not a bare list."""
        with tempfile.TemporaryDirectory() as tmp:
            path: str = self._write_hocon(
                tmp, "bad.hocon", "hello_world", [],
                interactions=[{"text": "hi", "response": {"sly_data": ["reservation_id"]}}],
            )
            with self.assertRaises(SystemExit) as ctx:
                self._load("hello_world", [path])
        self.assertEqual(ctx.exception.code, 1)

    def test_prefixed_agent_accepts_base_name_in_hocon(self) -> None:
        """--agent basic/hello_world matches hocons whose agent is hello_world."""
        profile: AgentProfile = self._load("basic/hello_world", self._fixture_hocons("hello_world"))
        self.assertEqual(profile.agent_name, "basic/hello_world")
        self.assertEqual(len(profile.prompts), len(self._fixture_hocons("hello_world")))

    def test_multiple_interactions_exits_1(self) -> None:
        """A multi-turn hocon is not a load-test prompt; abort."""
        with tempfile.TemporaryDirectory() as tmp:
            path: str = self._write_hocon(
                tmp, "multi.hocon", "hello_world", ["first", "second"],
            )
            with self.assertRaises(SystemExit) as ctx:
                self._load("hello_world", [path])
        self.assertEqual(ctx.exception.code, 1)

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
