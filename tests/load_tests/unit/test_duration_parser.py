
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
from typing import List
from unittest import TestCase

from tests.load_tests.duration import DurationParser


class TestDurationParser(TestCase):
    """
    Unit tests for DurationParser.parse(), format_seconds() and format_minutes_seconds().

    Every timeout flag runs through parse(), so a wrong answer silently
    changes what a run measures rather than failing visibly.
    """

    def test_bare_number_is_seconds(self) -> None:
        """
        A bare number is read as seconds.
        """
        self.assertEqual(DurationParser.parse("1200"), 1200)

    def test_suffixes_scale(self) -> None:
        """
        s/m/h scale the value.
        """
        self.assertEqual(DurationParser.parse("90s"), 90)
        self.assertEqual(DurationParser.parse("20m"), 1200)
        self.assertEqual(DurationParser.parse("2h"), 7200)

    def test_fractional_and_uppercase_are_accepted(self) -> None:
        """
        A fraction with an uppercase suffix still parses.
        """
        self.assertEqual(DurationParser.parse("0.5H"), 1800)

    def test_surrounding_whitespace_is_ignored(self) -> None:
        """
        Values arriving with whitespace parse the same.
        """
        self.assertEqual(DurationParser.parse("  20m  "), 1200)

    def test_result_is_whole_seconds(self) -> None:
        """
        Fractional seconds round rather than truncate.
        """
        self.assertEqual(DurationParser.parse("1.5"), 2)
        self.assertIsInstance(DurationParser.parse("1.5"), int)

    def test_zero_is_allowed(self) -> None:
        """
        Zero is a legitimate "no timeout" value for these flags.
        """
        self.assertEqual(DurationParser.parse("0"), 0)

    def test_empty_value_is_rejected(self) -> None:
        """
        An empty string is not a duration.
        """
        with self.assertRaises(ArgumentTypeError):
            DurationParser.parse("   ")

    def test_garbage_is_rejected(self) -> None:
        """
        Unparseable text raises the argparse error, not ValueError.
        """
        with self.assertRaises(ArgumentTypeError):
            DurationParser.parse("soon")

    def test_unknown_suffix_is_rejected(self) -> None:
        """
        A plausible-looking unit that is not supported is rejected.

        'd' is not in the unit table, so it must not be silently
        dropped and read as 5 seconds.
        """
        with self.assertRaises(ArgumentTypeError):
            DurationParser.parse("5d")

    def test_negative_is_rejected(self) -> None:
        """
        A negative timeout would abort every request immediately.
        """
        with self.assertRaises(ArgumentTypeError):
            DurationParser.parse("-5m")

    def test_format_seconds_uses_the_largest_even_unit(self) -> None:
        """
        format_seconds() uses the largest of s, m and h that divides the seconds evenly.
        """
        self.assertEqual(DurationParser.format_seconds(15), "15s")
        self.assertEqual(DurationParser.format_seconds(90), "90s")
        self.assertEqual(DurationParser.format_seconds(1200), "20m")
        self.assertEqual(DurationParser.format_seconds(5400), "90m")
        self.assertEqual(DurationParser.format_seconds(7200), "2h")

    def test_format_seconds_of_zero_is_seconds(self) -> None:
        """
        Zero is "0s", not "0h".
        """
        self.assertEqual(DurationParser.format_seconds(0), "0s")

    def test_format_seconds_text_parses_back(self) -> None:
        """
        parse() reads the format_seconds() text back as the same number of seconds.
        """
        seconds_values: List[int] = [0, 1, 15, 59, 60, 90, 900, 1200, 1500, 3600, 5400, 7200]
        seconds: int
        # Format each value, then parse the text back.
        for seconds in seconds_values:
            duration_text: str = DurationParser.format_seconds(seconds)
            self.assertEqual(DurationParser.parse(duration_text), seconds, duration_text)

    def test_format_minutes_seconds_under_a_minute_is_seconds(self) -> None:
        """
        A time under a minute prints as seconds only, and zero is "0s".
        """
        under_a_minute_text: str = DurationParser.format_minutes_seconds(45)
        zero_text: str = DurationParser.format_minutes_seconds(0)
        self.assertEqual(under_a_minute_text, "45s")
        self.assertEqual(zero_text, "0s")

    def test_format_minutes_seconds_over_a_minute(self) -> None:
        """
        105 seconds prints as "1m 45s", 120 seconds as "2m 0s" and 1205 seconds as "20m 5s".
        """
        minutes_and_seconds_text: str = DurationParser.format_minutes_seconds(105)
        whole_minutes_text: str = DurationParser.format_minutes_seconds(120)
        twenty_minutes_text: str = DurationParser.format_minutes_seconds(1205)
        self.assertEqual(minutes_and_seconds_text, "1m 45s")
        self.assertEqual(whole_minutes_text, "2m 0s")
        self.assertEqual(twenty_minutes_text, "20m 5s")

    def test_format_minutes_seconds_keeps_one_decimal_under_a_minute(self) -> None:
        """
        Under a minute one decimal stays: 0.44 is "0.4s", 12.36 is "12.4s" and 59.94 is "59.9s".
        From a minute on, seconds are whole: 59.96 is "1m 0s" and 105.4 is "1m 45s".
        """
        sub_second_text: str = DurationParser.format_minutes_seconds(0.44)
        seconds_text: str = DurationParser.format_minutes_seconds(12.36)
        just_under_text: str = DurationParser.format_minutes_seconds(59.94)
        rounded_up_text: str = DurationParser.format_minutes_seconds(59.96)
        over_a_minute_text: str = DurationParser.format_minutes_seconds(105.4)
        self.assertEqual(sub_second_text, "0.4s")
        self.assertEqual(seconds_text, "12.4s")
        self.assertEqual(just_under_text, "59.9s")
        self.assertEqual(rounded_up_text, "1m 0s")
        self.assertEqual(over_a_minute_text, "1m 45s")
