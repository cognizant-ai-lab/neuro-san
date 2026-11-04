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

# Whole re module: "from re import compile" would hide the builtin compile().
import re
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from tests.load_tests.monitoring.server_log_monitor import ServerLogMonitor


class ServerDurationReader:
    """
    Reads the server-side durations of the stage's primary agent requests from the server log.

    Parses the primary streaming_chat Start/Finish pairs written since the stage start position,
    so the heartbeat can report cumulative server-side min/avg/max durations.
    """

    def __init__(self, server_log_timing: Optional[Dict[str, Any]] = None) -> None:
        """
        Constructor.

        :param server_log_timing: Where to read server-side request timing, or None; each value may be None:
            "log_monitor": the ServerLogMonitor
            "log_start_position": the server log position where the stage started, from read_position()
            "primary_start_pattern": regex for the log line of a primary agent request starting
        """
        # Mixed values: a ServerLogMonitor, an int position and pattern strings.
        server_log_settings: Dict[str, Any] = {}
        if server_log_timing is not None:
            server_log_settings = server_log_timing
        self._log_monitor: Optional[ServerLogMonitor] = server_log_settings.get("log_monitor")
        self._log_start_position: Optional[int] = server_log_settings.get("log_start_position")
        primary_start_pattern: Optional[str] = server_log_settings.get("primary_start_pattern")
        self._primary_start_regex: Optional[re.Pattern] = None
        if primary_start_pattern:
            self._primary_start_regex = re.compile(primary_start_pattern)

    def read_durations(self) -> Optional[List[float]]:
        """
        Collect cumulative server-side per-request durations.

        Parses primary streaming_chat Start/Finish pairs from the
        server log since the stage start position.

        :return: Durations in seconds, or None when no server log is available
                 (so the caller can render ``n/a`` and distinguish "no data source" from "no requests yet")
        """
        if self._log_monitor is None or self._log_start_position is None:
            return None
        # Each pair has "agent" and "request_id" (str), and "start_seconds", "finish_seconds" and
        # "duration_seconds" (float).
        pairs: List[Dict[str, Any]] = []
        try:
            pairs = self._log_monitor.parse_streaming_chat_timing_since(self._log_start_position)
        except (OSError, ValueError):
            return []
        durations: List[float] = []
        pair: Dict[str, Any]
        # Keep the duration of each primary agent Start/Finish pair.
        for pair in pairs:
            if self._primary_start_regex is not None:
                agent: str = pair.get("agent", "")
                start_line: str = f"Start {agent}/streaming_chat"
                if not self._primary_start_regex.search(start_line):
                    continue
            duration_seconds: Optional[float] = pair.get("duration_seconds")
            if isinstance(duration_seconds, (int, float)) and duration_seconds > 0:
                duration_float: float = float(duration_seconds)
                durations.append(duration_float)
        return durations
