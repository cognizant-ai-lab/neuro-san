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

"""Build agent_cli subprocess commands and manage prompt files."""

import json
import logging
import os
import re
import tempfile
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

logger = logging.getLogger(__name__)


class CliBuilder:
    """Builds agent_cli subprocess commands and manages prompt files."""

    @staticmethod
    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def build_cli_command(
            host, port, agent_name, prompt_file,
            include_tokens=False, thinking_file=None,
    ) -> List[str]:
        """Build the agent_cli subprocess command list.

        When thinking_file is None, uses --no_thinking_file to avoid
        race conditions under concurrency.  When provided, enables
        per-request thinking dir for agent timing analysis.
        When include_tokens is True, adds --tokens for inline token
        accounting.
        """
        cmd = [
            "python", "-m", "neuro_san.client.agent_cli",
            "--http",
            "--host", host,
            "--port", str(port),
            "--agent", agent_name,
            "--first_prompt_file", prompt_file,
            "--one_shot",
        ]
        if thinking_file is not None:
            cmd.extend(["--thinking_file", thinking_file])
        else:
            cmd.append("--no_thinking_file")
        if include_tokens:
            cmd.append("--tokens")
        return cmd

    @staticmethod
    def write_prompt_file(global_request_id, prompt) -> str:
        """Write prompt text to a temporary file and return its path."""
        fd, prompt_file = tempfile.mkstemp(
            prefix=f"load_test_prompt_{global_request_id}_",
            suffix=".txt",
        )
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(prompt)
        return prompt_file

    @staticmethod
    def cleanup_prompt_file(prompt_file) -> None:
        """Remove the temporary prompt file."""
        try:
            os.remove(prompt_file)
        except OSError as exc:
            logger.debug("Could not remove prompt file: %s", exc)

    @staticmethod
    def parse_stdout_field(stdout, field_name) -> Optional[str]:
        """Extract a JSON field value from agent_cli stdout (sly_data output)."""
        match = re.search(rf'"{field_name}"\s*:\s*"([^"]+)"', stdout)
        if match:
            return match.group(1)
        return None

    @staticmethod
    def parse_token_accounting(stdout) -> Dict[str, Any]:
        """Extract Token Accounting JSON block from agent_cli stdout."""
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
