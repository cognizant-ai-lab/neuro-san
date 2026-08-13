
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
from argparse import ArgumentTypeError
from unittest import TestCase

from tests.load_tests.duration import DurationParser


class TestDurationParser(TestCase):
    """
    Unit tests for DurationParser.parse().

    Every timeout flag runs through this, so a wrong answer silently
    changes what a run measures rather than failing visibly.
    """

    def test_bare_number_is_seconds(self):
        """Existing numeric commands keep their meaning."""
        self.assertEqual(DurationParser.parse("1200"), 1200)

    def test_suffixes_scale(self):
        """s/m/h scale the value."""
        self.assertEqual(DurationParser.parse("90s"), 90)
        self.assertEqual(DurationParser.parse("20m"), 1200)
        self.assertEqual(DurationParser.parse("2h"), 7200)

    def test_fractional_and_uppercase_are_accepted(self):
        """A fraction with an uppercase suffix still parses."""
        self.assertEqual(DurationParser.parse("0.5H"), 1800)

    def test_surrounding_whitespace_is_ignored(self):
        """Values arriving with whitespace parse the same."""
        self.assertEqual(DurationParser.parse("  20m  "), 1200)

    def test_result_is_whole_seconds(self):
        """Fractional seconds round rather than truncate."""
        self.assertEqual(DurationParser.parse("1.5"), 2)
        self.assertIsInstance(DurationParser.parse("1.5"), int)

    def test_zero_is_allowed(self):
        """Zero is a legitimate "no timeout" value for these flags."""
        self.assertEqual(DurationParser.parse("0"), 0)

    def test_empty_value_is_rejected(self):
        """An empty string is not a duration."""
        with self.assertRaises(ArgumentTypeError):
            DurationParser.parse("   ")

    def test_garbage_is_rejected(self):
        """Unparseable text raises the argparse error, not ValueError."""
        with self.assertRaises(ArgumentTypeError):
            DurationParser.parse("soon")

    def test_unknown_suffix_is_rejected(self):
        """A plausible-looking unit that is not supported is rejected.

        'd' is not in the unit table, so it must not be silently
        dropped and read as 5 seconds.
        """
        with self.assertRaises(ArgumentTypeError):
            DurationParser.parse("5d")

    def test_negative_is_rejected(self):
        """A negative timeout would abort every request immediately."""
        with self.assertRaises(ArgumentTypeError):
            DurationParser.parse("-5m")
