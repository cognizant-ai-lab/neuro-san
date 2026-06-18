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

"""Parse agent thinking files to extract per-agent timing data.

Thinking files contain timestamped entries from each agent in the
network.  This module extracts the first and last timestamp per
agent file to calculate the time each agent spent processing.
"""

import logging
import os
import re
from typing import Dict

logger = logging.getLogger(__name__)

# Matches timestamp lines like: [AI Message from agent] @ 2024-01-15 10:30:45:
THINKING_TIMESTAMP_RE = re.compile(
    r"\[.*\]\s*@\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})\s*:",
)


class ThinkingParser:
    """Parse thinking directory files for per-agent timing."""

    @staticmethod
    def parse_thinking_dir(
            thinking_dir,
    ) -> Dict[str, float]:
        """Parse all files in a thinking directory.

        Returns a dict of agent_name -> duration_seconds.
        Duration is the time span from the first to the last
        timestamped entry in the agent's thinking file.
        """
        timing: Dict[str, float] = {}
        if not thinking_dir or not os.path.isdir(thinking_dir):
            return timing
        for filename in sorted(os.listdir(thinking_dir)):
            filepath = os.path.join(thinking_dir, filename)
            if not os.path.isfile(filepath):
                continue
            duration = ThinkingParser._parse_single_file(
                filepath,
            )
            if duration is not None:
                agent_name = ThinkingParser._filename_to_agent(
                    filename,
                )
                timing[agent_name] = duration
        return timing

    @staticmethod
    def _parse_single_file(filepath) -> float:
        """Extract the time span from a single thinking file.

        Returns the duration in seconds between the first and
        last timestamp, or None if fewer than 2 timestamps found.
        """
        from time import mktime  # pylint: disable=import-outside-toplevel
        from time import strptime  # pylint: disable=import-outside-toplevel

        timestamps = []
        try:
            with open(filepath, "r", encoding="utf-8") as fh:
                for line in fh:
                    match = THINKING_TIMESTAMP_RE.search(line)
                    if match:
                        ts_str = match.group(1)
                        try:
                            parsed = strptime(
                                ts_str, "%Y-%m-%d %H:%M:%S",
                            )
                            timestamps.append(mktime(parsed))
                        except ValueError:
                            continue
        except OSError:
            return None
        if len(timestamps) < 2:
            return None
        return timestamps[-1] - timestamps[0]

    @staticmethod
    def _filename_to_agent(filename) -> str:
        """Convert a thinking file name back to agent name.

        The thinking file processor replaces '/' with '__' in
        filenames.  This reverses that transformation.
        """
        return filename.replace("__", "/")
