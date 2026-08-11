
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
"""
See class comment for details.
"""
from __future__ import annotations

import random

from typing import Any
from typing import Dict
from typing import List


class PlaybackDelay:
    """
    Policy for the up-front delay applied before serving a cache hit during
    playback/hybrid, emulating how long the real LLM took to respond. This is
    distinct from inter-frame stream pacing (stream_replay_delay).

    Delay policies:
      none     -- no delay (serve immediately).
      recorded -- use the response's own recorded wall-clock latency: for
                  streams the time-to-first-token (first_byte_seconds), falling
                  back to total latency_seconds for one-shot responses. In
                  multi-response playback each rotated response carries its own
                  latency, so each is delayed by exactly what it took to record.
      fixed    -- a constant delay in seconds.
      random   -- a delay drawn uniformly from [min_seconds, max_seconds].
    """

    MODE_NONE: str = "none"
    MODE_RECORDED: str = "recorded"
    MODE_FIXED: str = "fixed"
    MODE_RANDOM: str = "random"
    ALL_MODES: List[str] = [MODE_NONE, MODE_RECORDED, MODE_FIXED, MODE_RANDOM]

    def __init__(
        self,
        mode: str = MODE_NONE,
        fixed_seconds: float = 0.0,
        min_seconds: float = 0.0,
        max_seconds: float = 0.0,
    ) -> None:
        """
        :param mode: One of ALL_MODES.
        :param fixed_seconds: Delay used in fixed mode.
        :param min_seconds: Lower bound used in random mode.
        :param max_seconds: Upper bound used in random mode.
        """
        self.mode: str = mode
        self.fixed_seconds: float = fixed_seconds
        self.min_seconds: float = min_seconds
        self.max_seconds: float = max_seconds

    def seconds_for(self, response: Dict[str, Any]) -> float:
        """
        Compute the delay to apply before serving a given recorded response.
        :param response: The recorded response dict being replayed.
        :return: The delay in seconds (>= 0); 0 means serve immediately.
        """
        if self.mode == self.MODE_RECORDED:
            # For streams, first_byte_seconds (time-to-first-token) is the natural
            # up-front delay; fall back to total latency_seconds (e.g. one-shot
            # JSON responses, which carry no first_byte_seconds).
            for field in ("first_byte_seconds", "latency_seconds"):
                recorded: Any = response.get(field)
                if isinstance(recorded, (int, float)) and recorded > 0:
                    return float(recorded)
            return 0.0
        if self.mode == self.MODE_FIXED:
            return max(0.0, self.fixed_seconds)
        if self.mode == self.MODE_RANDOM:
            return random.uniform(self.min_seconds, self.max_seconds)
        return 0.0
