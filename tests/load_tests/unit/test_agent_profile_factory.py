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

from glob import glob
from json import dump
from os.path import join
from tempfile import TemporaryDirectory
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from unittest import TestCase

from tests.load_tests.prompts.agent_profile import AgentProfile
from tests.load_tests.prompts.agent_profile_factory import AgentProfileFactory
from tests.load_tests.unit.load_test_unit_paths import LoadTestUnitPaths
from tests.load_tests.validation.load_test_abort_error import LoadTestAbortError


class TestAgentProfileFactory(TestCase):
    """
    Unit tests for AgentProfileFactory.create(), from hocon files and from the JSON profile.

    With hocon files the whole profile (prompts, success_fields,
    failure_patterns, estimated_tokens_per_request) comes from them;
    the JSON profile is not read.
    """

    def test_prompts_come_from_hocon_files(self) -> None:
        """
        Each fixture's interactions[].text becomes a prompt.
        """
        profile: AgentProfile = TestAgentProfileFactory._load_fixtures("hello_world")
        prompts: List[str] = profile.get_prompts()
        hocon_paths: List[str] = TestAgentProfileFactory._fixture_hocons("hello_world")
        prompt_count: int = len(prompts)
        hocon_count: int = len(hocon_paths)
        # One interaction per fixture
        self.assertEqual(prompt_count, hocon_count)
        self.assertIn("Hello, how are you today?", prompts)

    def test_agent_settings_come_from_hocons(self) -> None:
        """
        failure_patterns are read from the hocons, not the JSON.
        """
        profile: AgentProfile = TestAgentProfileFactory._load_fixtures("hello_world")
        estimated_tokens: Optional[int] = profile.get_estimated_tokens_per_request()
        success_fields: List[str] = profile.get_success_fields()
        failure_patterns: List[str] = profile.get_failure_patterns()
        failure_pattern_count: int = len(failure_patterns)
        self.assertIsNone(estimated_tokens)
        self.assertEqual(success_fields, [])
        self.assertIn("No fully-specified LLM found", failure_patterns)
        # Same pattern in every file -> listed once
        self.assertEqual(failure_pattern_count, 2)

    def test_responses_come_from_hocon_response_blocks(self) -> None:
        """
        Each fixture's response block is kept, parallel to its prompt.
        """
        profile: AgentProfile = TestAgentProfileFactory._load_fixtures("agent_network_designer")
        prompts: List[str] = profile.get_prompts()
        hocon_paths: List[str] = TestAgentProfileFactory._fixture_hocons("agent_network_designer")
        responses: List[Dict[str, Any]] = profile.get_responses()
        success_fields: List[str] = profile.get_success_fields()
        fourth_response: Dict[str, Any] = profile.get_response(3)
        sly_data_checks: Dict[str, Any] = fourth_response.get("sly_data")
        prompt_count: int = len(prompts)
        hocon_count: int = len(hocon_paths)
        response_count: int = len(responses)
        self.assertEqual(prompt_count, hocon_count)
        self.assertEqual(response_count, prompt_count)
        self.assertEqual(success_fields, [])
        self.assertEqual(
            sly_data_checks,
            {"agent_network_name": {"not_value": ""}, "agent_reservations": {"not_value": ""}},
        )

    def test_response_follows_prompt_selection(self) -> None:
        """
        get_response() picks the same pool entry as get_prompt().
        """
        profile: Optional[AgentProfile] = None
        with TemporaryDirectory() as temporary_directory:
            first: str = TestAgentProfileFactory._write_hocon(
                temporary_directory, "a.hocon", "x", [],
                interactions=[{"text": "one", "response": {"text": {"keywords": ["1"]}}}],
            )
            second: str = TestAgentProfileFactory._write_hocon(temporary_directory, "b.hocon", "x", ["two"])
            profile = TestAgentProfileFactory._load("x", [first, second])
        second_prompt: str = profile.get_prompt(1, allow_caching=True)
        second_response: Dict[str, Any] = profile.get_response(1)
        third_response: Dict[str, Any] = profile.get_response(2)
        same_prompt_response: Dict[str, Any] = profile.get_response(1, same_prompt=True)
        self.assertEqual(second_prompt, "two")
        self.assertEqual(second_response, {})
        self.assertEqual(third_response, {"text": {"keywords": ["1"]}})
        self.assertEqual(same_prompt_response, {"text": {"keywords": ["1"]}})

    def test_json_success_fields_become_not_value_checks(self) -> None:
        """
        A JSON profile's success_fields turn into sly_data not_value checks.
        """
        profile: AgentProfile = AgentProfileFactory().create("agent_network_designer",
                                                             project_root=LoadTestUnitPaths.PROJECT_ROOT)
        first_response: Dict[str, Any] = profile.get_response(0)
        self.assertEqual(
            first_response,
            {"sly_data": {"agent_reservations": {"not_value": ""}, "agent_network_name": {"not_value": ""}}},
        )

    def test_json_profile_not_an_object_aborts_with_code_1(self) -> None:
        """
        A JSON profile that is a list, not an object, aborts the run.
        """
        with TemporaryDirectory() as temporary_directory:
            json_path: str = join(temporary_directory, "hello_world.json")
            with open(json_path, "w", encoding="utf-8") as file_handle:
                dump(["Hello"], file_handle)
            with self.assertRaises(LoadTestAbortError) as caught:
                AgentProfileFactory().create("hello_world", profile_path=temporary_directory)
        exit_code: int = caught.exception.get_exit_code()
        self.assertEqual(exit_code, 1)

    def test_json_profile_not_needed_with_hocons(self) -> None:
        """
        An agent with no JSON profile loads fine from hocons alone.
        """
        profile: Optional[AgentProfile] = None
        with TemporaryDirectory() as temporary_directory:
            path: str = TestAgentProfileFactory._write_hocon(
                temporary_directory, "only.hocon", "no_such_agent", ["hi"],
                failure_patterns=["oops"], estimated_tokens_per_request=42,
            )
            profile = TestAgentProfileFactory._load("no_such_agent", [path])
        prompts: List[str] = profile.get_prompts()
        failure_patterns: List[str] = profile.get_failure_patterns()
        success_fields: List[str] = profile.get_success_fields()
        estimated_tokens: Optional[int] = profile.get_estimated_tokens_per_request()
        self.assertEqual(prompts, ["hi"])
        self.assertEqual(failure_patterns, ["oops"])
        self.assertEqual(success_fields, [])
        self.assertEqual(estimated_tokens, 42)

    def test_sly_data_list_aborts_with_code_1(self) -> None:
        """
        response.sly_data must be a field -> check map, not a bare list.
        """
        with TemporaryDirectory() as temporary_directory:
            path: str = TestAgentProfileFactory._write_hocon(
                temporary_directory, "bad.hocon", "hello_world", [],
                interactions=[{"text": "hi", "response": {"sly_data": ["reservation_id"]}}],
            )
            with self.assertRaises(LoadTestAbortError) as caught:
                TestAgentProfileFactory._load("hello_world", [path])
        exit_code: int = caught.exception.get_exit_code()
        self.assertEqual(exit_code, 1)

    def test_response_not_a_map_aborts_with_code_1(self) -> None:
        """
        response itself must be a map, not a string or list.
        """
        with TemporaryDirectory() as temporary_directory:
            path: str = TestAgentProfileFactory._write_hocon(
                temporary_directory, "bad.hocon", "hello_world", [],
                interactions=[{"text": "hi", "response": "reservation_id"}],
            )
            with self.assertRaises(LoadTestAbortError) as caught:
                TestAgentProfileFactory._load("hello_world", [path])
        exit_code: int = caught.exception.get_exit_code()
        self.assertEqual(exit_code, 1)

    def test_prefixed_agent_accepts_base_name_in_hocon(self) -> None:
        """
        --agent basic/hello_world matches hocons whose agent is hello_world.
        """
        hocon_paths: List[str] = TestAgentProfileFactory._fixture_hocons("hello_world")
        profile: AgentProfile = TestAgentProfileFactory._load("basic/hello_world", hocon_paths)
        agent_name: str = profile.get_agent_name()
        self.assertEqual(agent_name, "basic/hello_world")
        prompts: List[str] = profile.get_prompts()
        prompt_count: int = len(prompts)
        hocon_count: int = len(hocon_paths)
        self.assertEqual(prompt_count, hocon_count)

    def test_multiple_interactions_aborts_with_code_1(self) -> None:
        """
        A multi-turn hocon is not a load-test prompt; abort.
        """
        with TemporaryDirectory() as temporary_directory:
            path: str = TestAgentProfileFactory._write_hocon(temporary_directory, "multi.hocon", "hello_world",
                                                             ["first", "second"])
            with self.assertRaises(LoadTestAbortError) as caught:
                TestAgentProfileFactory._load("hello_world", [path])
        exit_code: int = caught.exception.get_exit_code()
        self.assertEqual(exit_code, 1)

    def test_agent_mismatch_aborts_with_code_1(self) -> None:
        """
        A hocon for a different agent aborts the run.
        """
        with TemporaryDirectory() as temporary_directory:
            path: str = TestAgentProfileFactory._write_hocon(temporary_directory, "other.hocon", "music_nerd", ["hi"])
            with self.assertRaises(LoadTestAbortError) as caught:
                TestAgentProfileFactory._load("hello_world", [path])
        exit_code: int = caught.exception.get_exit_code()
        self.assertEqual(exit_code, 1)

    def test_no_text_anywhere_aborts_with_code_1(self) -> None:
        """
        No prompts at all aborts the run.
        """
        with TemporaryDirectory() as temporary_directory:
            path: str = TestAgentProfileFactory._write_hocon(temporary_directory, "empty.hocon", "hello_world", [])
            with self.assertRaises(LoadTestAbortError) as caught:
                TestAgentProfileFactory._load("hello_world", [path])
        exit_code: int = caught.exception.get_exit_code()
        self.assertEqual(exit_code, 1)

    @staticmethod
    def _fixture_hocons(agent: str) -> List[str]:
        """
        Sorted hocon paths under the default fixtures dir for one agent.

        :param agent: Agent name, also the fixtures subfolder
        :return: Sorted *.hocon paths in that subfolder
        """
        pattern: str = join(LoadTestUnitPaths.FIXTURES_HOCON_DIR, agent, "*.hocon")
        hocon_paths: List[str] = glob(pattern)
        sorted_paths: List[str] = sorted(hocon_paths)
        return sorted_paths

    @classmethod
    def _load_fixtures(cls, agent: str) -> AgentProfile:
        """
        Load the profile from the checked-in fixtures of one agent.

        :param agent: Agent name, also the fixtures subfolder
        :return: Profile built from that agent's fixture hocons
        """
        return cls._load(agent, cls._fixture_hocons(agent))

    @staticmethod
    def _load(agent: str, hocon_files: List[str]) -> AgentProfile:
        """
        Load the profile from the given hocons.

        :param agent: Agent name passed to AgentProfileFactory
        :param hocon_files: Test-case hocon paths to read prompts from
        :return: Profile built from those hocons
        """
        factory: AgentProfileFactory = AgentProfileFactory()
        profile: AgentProfile = factory.create(agent, project_root=LoadTestUnitPaths.PROJECT_ROOT,
                                               hocon_files=hocon_files)
        return profile

    @staticmethod
    def _write_hocon(folder: str, name: str, agent: str, texts: List[str], **extra: Any) -> str:
        """
        Write a minimal test-case hocon (JSON is valid hocon) and return its path.

        :param folder: Directory to write the file in
        :param name: File name
        :param agent: Value of the test case's agent key
        :param texts: One interaction per text
        :param extra: Extra or replacement top-level test-case keys, such as failure_patterns or interactions
        :return: Path of the written file
        """
        path: str = join(folder, name)
        interactions: List[Dict[str, str]] = []
        text: str
        # One interaction per text.
        for text in texts:
            interactions.append({"text": text})
        test_case: Dict[str, Any] = {
            "agent": agent,
            "interactions": interactions,
        }
        test_case.update(extra)
        with open(path, "w", encoding="utf-8") as file_handle:
            dump(test_case, file_handle)
        return path
