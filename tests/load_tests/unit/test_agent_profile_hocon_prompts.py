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
from tests.load_tests.prompts.agent_profile_factory import AgentProfileFactory

# Real fixtures, not mocks: tests/fixtures/load_tests/<agent>/*.hocon
PROJECT_ROOT: str = TOP_LEVEL_DIR.get_file_in_basis("..")


class TestAgentProfileHoconPrompts(TestCase):
    """
    Unit tests for AgentProfileFactory.create(..., hocon_files=...).

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
        return AgentProfileFactory().create(
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
        self.assertEqual(len(profile.get_prompts()), len(self._fixture_hocons("hello_world")))
        self.assertIn("Hello, how are you today?", profile.get_prompts())

    def test_agent_settings_come_from_hocons(self) -> None:
        """failure_patterns are read from the hocons, not the JSON."""
        profile: AgentProfile = self._load_fixtures("hello_world")
        self.assertIsNone(profile.get_estimated_tokens_per_request())
        self.assertEqual(profile.get_success_fields(), [])
        self.assertIn("No fully-specified LLM found", profile.get_failure_patterns())
        # Same pattern in every file -> listed once
        self.assertEqual(len(profile.get_failure_patterns()), 2)

    def test_responses_come_from_hocon_response_blocks(self) -> None:
        """
        Each fixture's response block is kept, parallel to its prompt.
        """
        profile: AgentProfile = self._load_fixtures("agent_network_designer")
        self.assertEqual(len(profile.get_prompts()), len(self._fixture_hocons("agent_network_designer")))
        self.assertEqual(len(profile.get_responses()), len(profile.get_prompts()))
        self.assertEqual(profile.get_success_fields(), [])
        self.assertEqual(
            profile.get_response(3).get("sly_data"),
            {"agent_network_name": {"not_value": ""}, "agent_reservations": {"not_value": ""}},
        )

    def test_response_follows_prompt_selection(self) -> None:
        """
        get_response() picks the same pool entry as get_prompt().
        """
        with tempfile.TemporaryDirectory() as tmp:
            first: str = self._write_hocon(
                tmp, "a.hocon", "x", [],
                interactions=[{"text": "one", "response": {"text": {"keywords": ["1"]}}}],
            )
            second: str = self._write_hocon(tmp, "b.hocon", "x", ["two"])
            profile: AgentProfile = self._load("x", [first, second])
        self.assertEqual(profile.get_prompt(1, allow_caching=True), "two")
        self.assertEqual(profile.get_response(1), {})
        self.assertEqual(profile.get_response(2), {"text": {"keywords": ["1"]}})
        self.assertEqual(profile.get_response(1, same_prompt=True), {"text": {"keywords": ["1"]}})

    def test_json_success_fields_become_not_value_checks(self) -> None:
        """
        A JSON profile's success_fields turn into sly_data not_value checks.
        """
        profile: AgentProfile = AgentProfileFactory().create(
            "agent_network_designer", project_root=PROJECT_ROOT,
        )
        self.assertEqual(
            profile.get_response(0),
            {"sly_data": {"agent_reservations": {"not_value": ""}, "agent_network_name": {"not_value": ""}}},
        )

    def test_json_profile_not_needed_with_hocons(self) -> None:
        """An agent with no JSON profile loads fine from hocons alone."""
        with tempfile.TemporaryDirectory() as tmp:
            path: str = self._write_hocon(
                tmp, "only.hocon", "no_such_agent", ["hi"],
                failure_patterns=["oops"], estimated_tokens_per_request=42,
            )
            profile: AgentProfile = self._load("no_such_agent", [path])
        self.assertEqual(profile.get_prompts(), ["hi"])
        self.assertEqual(profile.get_failure_patterns(), ["oops"])
        self.assertEqual(profile.get_success_fields(), [])
        self.assertEqual(profile.get_estimated_tokens_per_request(), 42)

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

    def test_response_not_a_map_exits_1(self) -> None:
        """response itself must be a map, not a string or list."""
        with tempfile.TemporaryDirectory() as tmp:
            path: str = self._write_hocon(
                tmp, "bad.hocon", "hello_world", [],
                interactions=[{"text": "hi", "response": "reservation_id"}],
            )
            with self.assertRaises(SystemExit) as ctx:
                self._load("hello_world", [path])
        self.assertEqual(ctx.exception.code, 1)

    def test_prefixed_agent_accepts_base_name_in_hocon(self) -> None:
        """--agent basic/hello_world matches hocons whose agent is hello_world."""
        profile: AgentProfile = self._load("basic/hello_world", self._fixture_hocons("hello_world"))
        self.assertEqual(profile.agent_name, "basic/hello_world")
        self.assertEqual(len(profile.get_prompts()), len(self._fixture_hocons("hello_world")))

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
