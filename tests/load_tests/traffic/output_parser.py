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
    def parse_stdout_field(stdout, field_name) -> Optional[str]:
        """Extract a JSON field value from agent response text."""
        match = re.search(rf'"{field_name}"\s*:\s*"([^"]+)"', stdout)
        if match:
            return match.group(1)
        return None

    @staticmethod
    def parse_token_accounting(stdout) -> Dict[str, Any]:
        """Extract Token Accounting JSON block from agent response text."""
        marker = "Token Accounting:"
        idx = stdout.find(marker)
        if idx < 0:
            return {}
        json_start = stdout.find("{", idx)
        if json_start < 0:
            return {}
        depth = 0
        json_end = json_start
        for i in range(json_start, len(stdout)):
            if stdout[i] == "{":
                depth += 1
            elif stdout[i] == "}":
                depth -= 1
                if depth == 0:
                    json_end = i + 1
                    break
        try:
            return json.loads(stdout[json_start:json_end])
        except (json.JSONDecodeError, ValueError):
            return {}

    @staticmethod
    def last_stderr_line(stderr) -> str:
        """Extract the last line of stderr for error reporting."""
        stripped = stderr.strip() if stderr else ""
        if not stripped:
            return ""
        return stripped.rsplit("\n", maxsplit=1)[-1]
