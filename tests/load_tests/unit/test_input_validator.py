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

from argparse import Namespace
from os import listdir
from os import mkdir
from os.path import dirname
from os.path import join
from tempfile import TemporaryDirectory
from typing import List
from typing import Optional
from unittest import TestCase

from tests.load_tests.load_test_constants import LoadTestConstants
from tests.load_tests.unit.load_test_unit_paths import LoadTestUnitPaths
from tests.load_tests.validation.input_validator import InputValidator
from tests.load_tests.validation.load_test_abort_error import LoadTestAbortError


class TestInputValidator(TestCase):
    """
    Unit tests for InputValidator: resolve_max_requests(), resolve_stages() and validate_fixtures_hocon_dir().

    Non-positive counts must be rejected before anything runs: the cost probe fires a real LLM request, so reaching
    it with a cap of zero spends tokens on a run that then does nothing. --stages is raw user input, so malformed
    values must produce a clear exit rather than a ValueError traceback. --fixtures-hocon-dir names the parent
    fixtures directory; the agent subfolder comes from --agent. A wrong path must exit clearly, not run the load test
    against the JSON prompts by mistake.
    """

    # Real fixtures, not mocks: tests/fixtures/load_tests/hello_world/*.hocon
    HELLO_WORLD_FIXTURES: str = join(LoadTestUnitPaths.FIXTURES_HOCON_DIR, "hello_world")

    def test_cap_is_stage_total_times_rounds(self) -> None:
        """
        The default cap covers every stage of every round.
        """
        validator: InputValidator = TestInputValidator._max_requests_validator(num_rounds=3)

        self.assertEqual(validator.resolve_max_requests([2, 4, 8]), 42)

    def test_explicit_max_requests_wins(self) -> None:
        """
        --max-requests overrides the computed cap.
        """
        validator: InputValidator = TestInputValidator._max_requests_validator(num_rounds=3, max_requests=5)

        self.assertEqual(validator.resolve_max_requests([2, 4, 8]), 5)

    def test_zero_rounds_exits(self) -> None:
        """
        --num-rounds 0 must exit before the probe spends tokens.
        """
        validator: InputValidator = TestInputValidator._max_requests_validator(num_rounds=0)

        with self.assertRaises(LoadTestAbortError) as caught:
            validator.resolve_max_requests([3])

        self.assertEqual(caught.exception.get_exit_code(), 1)

    def test_negative_rounds_exits(self) -> None:
        """
        A negative --num-rounds is rejected the same way.
        """
        validator: InputValidator = TestInputValidator._max_requests_validator(num_rounds=-3)

        with self.assertRaises(LoadTestAbortError) as caught:
            validator.resolve_max_requests([3])

        self.assertEqual(caught.exception.get_exit_code(), 1)

    def test_rounds_are_validated_before_explicit_max_requests(self) -> None:
        """
        --max-requests must not mask an invalid --num-rounds.

        The rounds check runs first, so passing both does not slip
        past validation through the early return.
        """
        validator: InputValidator = TestInputValidator._max_requests_validator(num_rounds=0, max_requests=5)

        with self.assertRaises(LoadTestAbortError) as caught:
            validator.resolve_max_requests([3])

        self.assertEqual(caught.exception.get_exit_code(), 1)

    def test_zero_max_requests_exits(self) -> None:
        """
        --max-requests 0 caps the run at nothing, so it is rejected.
        """
        validator: InputValidator = TestInputValidator._max_requests_validator(max_requests=0)

        with self.assertRaises(LoadTestAbortError) as caught:
            validator.resolve_max_requests([3])

        self.assertEqual(caught.exception.get_exit_code(), 1)

    def test_flat_mode_is_a_single_stage(self) -> None:
        """
        Without --ramp the run is one stage of --num-requests.
        """
        validator: InputValidator = TestInputValidator._stages_validator(num_requests=7)

        self.assertEqual(validator.resolve_stages(), [7])

    def test_ramp_without_stages_uses_defaults(self) -> None:
        """
        --ramp alone falls back to the built-in stage list.
        """
        validator: InputValidator = TestInputValidator._stages_validator(ramp=True)

        self.assertEqual(validator.resolve_stages(), list(LoadTestConstants.DEFAULT_STAGES))

    def test_stages_are_parsed_and_trailing_commas_ignored(self) -> None:
        """
        Whitespace and a trailing comma are tolerated.
        """
        validator: InputValidator = TestInputValidator._stages_validator(ramp=True, stages=" 2, 4 ,8, ")

        self.assertEqual(validator.resolve_stages(), [2, 4, 8])

    def test_non_integer_stages_exit(self) -> None:
        """
        Garbage in --stages exits instead of raising ValueError.
        """
        validator: InputValidator = TestInputValidator._stages_validator(ramp=True, stages="2,abc")

        with self.assertRaises(LoadTestAbortError) as caught:
            validator.resolve_stages()

        self.assertEqual(caught.exception.get_exit_code(), 1)

    def test_non_positive_stages_exit(self) -> None:
        """
        A zero stage would run an empty stage, so it is rejected.
        """
        validator: InputValidator = TestInputValidator._stages_validator(ramp=True, stages="2,0,8")

        with self.assertRaises(LoadTestAbortError) as caught:
            validator.resolve_stages()

        self.assertEqual(caught.exception.get_exit_code(), 1)

    def test_zero_num_requests_exits(self) -> None:
        """
        --num-requests 0 is rejected in flat mode.
        """
        validator: InputValidator = TestInputValidator._stages_validator(num_requests=0)

        with self.assertRaises(LoadTestAbortError) as caught:
            validator.resolve_stages()

        self.assertEqual(caught.exception.get_exit_code(), 1)

    def test_flag_absent_returns_empty_list(self) -> None:
        """
        No flag means prompts come from the JSON profile.
        """
        validator: InputValidator = TestInputValidator._fixtures_validator()
        files: List[str] = validator.validate_fixtures_hocon_dir()
        self.assertEqual(files, [])

    def test_default_dir_resolves_hello_world_fixtures(self) -> None:
        """
        DIR default + agent name -> tests/fixtures/load_tests/hello_world.
        """
        validator: InputValidator = TestInputValidator._fixtures_validator(
            fixtures_hocon_dir=LoadTestConstants.DEFAULT_FIXTURES_HOCON_DIR)
        files: List[str] = validator.validate_fixtures_hocon_dir()

        expected: List[str] = []
        name: str
        # Expect every *.hocon file of the hello_world fixtures, sorted.
        for name in listdir(TestInputValidator.HELLO_WORLD_FIXTURES):
            if name.endswith(".hocon"):
                expected.append(join(TestInputValidator.HELLO_WORLD_FIXTURES, name))
        expected.sort()
        self.assertEqual(files, expected)
        self.assertEqual(len(files), 5)

    def test_prefixed_agent_uses_base_name(self) -> None:
        """
        basic/hello_world resolves to the hello_world subfolder.
        """
        validator: InputValidator = TestInputValidator._fixtures_validator(
            agent="basic/hello_world", fixtures_hocon_dir=LoadTestConstants.DEFAULT_FIXTURES_HOCON_DIR)
        files: List[str] = validator.validate_fixtures_hocon_dir()
        self.assertEqual(len(files), 5)
        file_path: str
        # Every file is in the hello_world fixtures directory.
        for file_path in files:
            self.assertTrue(file_path.startswith(TestInputValidator.HELLO_WORLD_FIXTURES), file_path)

    def test_absolute_dir_is_used_as_is(self) -> None:
        """
        An absolute DIR ignores --project-root.
        """
        fixtures_hocon_dir: str = dirname(TestInputValidator.HELLO_WORLD_FIXTURES)
        validator: InputValidator = TestInputValidator._fixtures_validator(
            fixtures_hocon_dir=fixtures_hocon_dir, project_root="/nonexistent")
        files: List[str] = validator.validate_fixtures_hocon_dir()
        self.assertEqual(len(files), 5)

    def test_missing_agent_dir_exits(self) -> None:
        """
        No <DIR>/<agent>/ folder -> exit 1.
        """
        validator: InputValidator = TestInputValidator._fixtures_validator(
            agent="no_such_agent", fixtures_hocon_dir=LoadTestConstants.DEFAULT_FIXTURES_HOCON_DIR)
        with self.assertRaises(LoadTestAbortError) as caught:
            validator.validate_fixtures_hocon_dir()
        self.assertEqual(caught.exception.get_exit_code(), 1)

    def test_empty_agent_dir_exits(self) -> None:
        """
        Folder exists but holds no *.hocon -> exit 1.
        """
        with TemporaryDirectory() as parent:
            mkdir(join(parent, "hello_world"))
            validator: InputValidator = TestInputValidator._fixtures_validator(fixtures_hocon_dir=parent)
            with self.assertRaises(LoadTestAbortError) as caught:
                validator.validate_fixtures_hocon_dir()
        self.assertEqual(caught.exception.get_exit_code(), 1)

    @staticmethod
    def _max_requests_validator(num_rounds: int = 1, max_requests: Optional[int] = None) -> InputValidator:
        """
        Build a validator with only the args resolve_max_requests() reads.

        :param num_rounds: --num-rounds value
        :param max_requests: --max-requests value; None when not given
        :return: Validator over those args
        """
        args: Namespace = Namespace(num_rounds=num_rounds, max_requests=max_requests)
        return InputValidator(args)

    @staticmethod
    def _stages_validator(ramp: bool = False, stages: Optional[str] = None, num_requests: int = 3) -> InputValidator:
        """
        Build a validator with only the args resolve_stages() reads.

        :param ramp: --ramp value
        :param stages: --stages CSV; None when not given
        :param num_requests: --num-requests value
        :return: Validator over those args
        """
        args: Namespace = Namespace(ramp=ramp, stages=stages, num_requests=num_requests)
        return InputValidator(args)

    @staticmethod
    def _fixtures_validator(agent: str = "hello_world", fixtures_hocon_dir: Optional[str] = None,
                            project_root: Optional[str] = LoadTestUnitPaths.PROJECT_ROOT) -> InputValidator:
        """
        Build a validator with only the args validate_fixtures_hocon_dir() reads.

        :param agent: --agent value
        :param fixtures_hocon_dir: --fixtures-hocon-dir value; None when not given
        :param project_root: --project-root value
        :return: Validator over those args
        """
        args: Namespace = Namespace(agent=agent, fixtures_hocon_dir=fixtures_hocon_dir, project_root=project_root)
        return InputValidator(args)
