
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
from unittest import TestCase

from tests.load_tests.config import DEFAULT_STAGES
from tests.load_tests.validation.input_validator import InputValidator


class TestResolveStages(TestCase):
    """
    Unit tests for InputValidator.resolve_stages().

    --stages is raw user input, so malformed values must produce a
    clear exit rather than a ValueError traceback.
    """

    @staticmethod
    def _validator(*, ramp=False, stages=None, num_requests=3):
        """Build a validator with only the args these methods read."""
        return InputValidator(Namespace(
            ramp=ramp,
            stages=stages,
            num_requests=num_requests,
        ))

    def test_flat_mode_is_a_single_stage(self):
        """Without --ramp the run is one stage of --num-requests."""
        validator = self._validator(num_requests=7)

        self.assertEqual(validator.resolve_stages(), [7])

    def test_ramp_without_stages_uses_defaults(self):
        """--ramp alone falls back to the built-in stage list."""
        validator = self._validator(ramp=True)

        self.assertEqual(validator.resolve_stages(), list(DEFAULT_STAGES))

    def test_stages_are_parsed_and_trailing_commas_ignored(self):
        """Whitespace and a trailing comma are tolerated."""
        validator = self._validator(ramp=True, stages=" 2, 4 ,8, ")

        self.assertEqual(validator.resolve_stages(), [2, 4, 8])

    def test_non_integer_stages_exit(self):
        """Garbage in --stages exits instead of raising ValueError."""
        validator = self._validator(ramp=True, stages="2,abc")

        with self.assertRaises(SystemExit) as caught:
            validator.resolve_stages()

        self.assertEqual(caught.exception.code, 1)

    def test_non_positive_stages_exit(self):
        """A zero stage would run an empty stage, so it is rejected."""
        validator = self._validator(ramp=True, stages="2,0,8")

        with self.assertRaises(SystemExit) as caught:
            validator.resolve_stages()

        self.assertEqual(caught.exception.code, 1)

    def test_zero_num_requests_exits(self):
        """--num-requests 0 is rejected in flat mode."""
        validator = self._validator(num_requests=0)

        with self.assertRaises(SystemExit) as caught:
            validator.resolve_stages()

        self.assertEqual(caught.exception.code, 1)
