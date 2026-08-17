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

"""Parse human-friendly timeout durations into whole seconds."""

import argparse


class DurationParser:
    """Parse human-friendly durations into whole seconds.

    A bare number is seconds (so existing commands are unchanged); an
    optional ``s``/``m``/``h`` suffix scales it, e.g. ``90s``, ``20m``,
    ``2h``, ``0.5h``.  Designed to be used as an argparse ``type``.
    """

    _UNITS = {"s": 1, "m": 60, "h": 3600}

    @staticmethod
    def parse(value: str) -> int:
        """Return whole seconds for ``value``; raise on bad input."""
        text = str(value).strip().lower()
        if not text:
            raise argparse.ArgumentTypeError("empty duration")
        unit = 1
        if text[-1] in DurationParser._UNITS:
            unit = DurationParser._UNITS[text[-1]]
            text = text[:-1]
        try:
            seconds = float(text) * unit
        except ValueError as exc:
            raise argparse.ArgumentTypeError(
                f"invalid duration '{value}': use seconds or a s/m/h "
                "suffix, e.g. 90s, 20m, 2h"
            ) from exc
        if seconds < 0:
            raise argparse.ArgumentTypeError(
                f"duration must be non-negative: '{value}'"
            )
        return int(round(seconds))
