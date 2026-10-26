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
from typing import Dict


class DurationParser:
    """
    Parse human-friendly durations into whole seconds, and format whole seconds back into that form.

    A bare number is seconds; an optional ``s``/``m``/``h`` suffix scales it,
    e.g. ``90s``, ``20m``, ``2h``, ``0.5h``.  parse() is designed to be used as an argparse ``type``.
    """

    _UNITS: Dict[str, int] = {"s": 1, "m": 60, "h": 3600}

    @staticmethod
    def parse(value: str) -> int:
        """
        Return whole seconds for ``value``; raise on bad input.

        :param value: Seconds, or a number with an s, m or h suffix
        :return: Whole seconds
        """
        text: str = str(value).strip().lower()
        if not text:
            raise ArgumentTypeError("empty duration")
        unit: int = 1
        # pylint: disable=consider-iterating-dictionary
        if text[-1] in DurationParser._UNITS.keys():
            unit = DurationParser._UNITS.get(text[-1])
            text = text[:-1]
        seconds: float = 0.0
        try:
            seconds = float(text) * unit
        except ValueError as exc:
            raise ArgumentTypeError(
                f"invalid duration '{value}': use seconds or a s/m/h "
                "suffix, e.g. 90s, 20m, 2h"
            ) from exc
        if seconds < 0:
            raise ArgumentTypeError(f"duration must be non-negative: '{value}'")
        return int(round(seconds))

    @staticmethod
    def format_seconds(seconds: int) -> str:
        """
        Return seconds in the s/m/h form that parse() reads, using the largest unit that divides them evenly.

        :param seconds: Whole seconds, e.g. 1200
        :return: The duration text, e.g. "20m" for 1200, "15s" for 15 and "0s" for 0
        """
        duration_text: str = f"{seconds}s"
        whole_units: int = 0
        suffix: str
        unit_seconds: int
        # Keep the last (largest) unit that divides the seconds evenly; _UNITS runs from s to h.
        for suffix, unit_seconds in DurationParser._UNITS.items():
            whole_units = int(seconds / unit_seconds)
            if whole_units > 0 and whole_units * unit_seconds == seconds:
                duration_text = f"{whole_units}{suffix}"
        return duration_text

    @staticmethod
    def format_minutes_seconds(seconds: float) -> str:
        """
        Return a time waited or taken as minutes and seconds.

        :param seconds: Duration in seconds, e.g. 105
        :return: The duration text, e.g. "1m 45s" for 105, "2m 0s" for 120, "45s" for 45 and "0.4s" for 0.4
        """
        tenths_seconds: float = round(seconds, 1)
        seconds_per_minute: int = DurationParser._UNITS.get("m")
        # Under a minute, keep one decimal without a trailing ".0": 0.4 is "0.4s" and 45.0 is "45s".
        duration_text: str = f"{tenths_seconds:g}s"
        if tenths_seconds >= seconds_per_minute:
            whole_seconds: int = round(seconds)
            # Whole minutes: int() drops the fraction, so 105 seconds is 1 minute.
            minutes: int = int(whole_seconds / seconds_per_minute)
            remainder_seconds: int = whole_seconds - minutes * seconds_per_minute
            duration_text = f"{minutes}m {remainder_seconds}s"
        return duration_text
