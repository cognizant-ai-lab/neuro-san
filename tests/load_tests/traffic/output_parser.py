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

"""Parse agent response text: sly_data fields, token accounting, error lines."""

import json
import re
from typing import Any
from typing import Dict
from typing import Optional


class OutputParser:
    """Parses agent response fields and token accounting."""

    @staticmethod
    def parse_stdout_field(stdout: str, field_name: str) -> Optional[str]:
        """
        Extract a JSON field value from agent response text.

        :param stdout: Agent response text
        :param field_name: JSON field name to look for
        :return: The field's string value, or None when it is not found
        """
        match: Optional[re.Match] = re.search(rf'"{field_name}"\s*:\s*"([^"]+)"', stdout)
        if match:
            return match.group(1)
        return None

    @staticmethod
    def parse_token_accounting(stdout: str) -> Dict[str, Any]:
        """
        Extract Token Accounting JSON block from agent response text.

        :param stdout: Agent response text
        :return: The parsed Token Accounting block, or {} when it is missing or invalid
        """
        marker: str = "Token Accounting:"
        marker_index: int = stdout.find(marker)
        if marker_index < 0:
            return {}
        json_start: int = stdout.find("{", marker_index)
        if json_start < 0:
            return {}
        depth: int = 0
        json_end: int = json_start
        for char_index in range(json_start, len(stdout)):
            if stdout[char_index] == "{":
                depth += 1
            elif stdout[char_index] == "}":
                depth -= 1
                if depth == 0:
                    json_end = char_index + 1
                    break
        try:
            return json.loads(stdout[json_start:json_end])
        except (json.JSONDecodeError, ValueError):
            return {}

    @staticmethod
    def last_stderr_line(stderr: Optional[str]) -> str:
        """
        Extract the last line of stderr for error reporting.

        :param stderr: Captured stderr, or None
        :return: Last line of stderr, or "" when it is empty
        """
        stripped: str = stderr.strip() if stderr else ""
        if not stripped:
            return ""
        return stripped.rsplit("\n", maxsplit=1)[-1]
