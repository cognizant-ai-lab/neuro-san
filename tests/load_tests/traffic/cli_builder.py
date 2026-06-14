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

import logging
import os
import re
import tempfile
from typing import List
from typing import Optional

logger = logging.getLogger(__name__)


class CliBuilder:
    """Builds agent_cli subprocess commands and manages prompt files."""

    @staticmethod
    def build_cli_command(host, port, agent_name, prompt_file) -> List[str]:
        """Build the agent_cli subprocess command list.

        Includes --no_thinking_file to avoid race conditions under concurrency.
        """
        return [
            "python", "-m", "neuro_san.client.agent_cli",
            "--http",
            "--host", host,
            "--port", str(port),
            "--agent", agent_name,
            "--first_prompt_file", prompt_file,
            "--one_shot",
            "--no_thinking_file",
        ]

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
    def cleanup_prompt_file(prompt_file):
        """Remove the temporary prompt file."""
        try:
            os.remove(prompt_file)
        except OSError:
            pass

    @staticmethod
    def parse_stdout_field(stdout, field_name) -> Optional[str]:
        """Extract a JSON field value from agent_cli stdout (sly_data output)."""
        match = re.search(rf'"{field_name}"\s*:\s*"([^"]+)"', stdout)
        if match:
            return match.group(1)
        return None

    @staticmethod
    def last_stderr_line(stderr) -> str:
        """Extract the last line of stderr for error reporting."""
        stripped = stderr.strip() if stderr else ""
        if not stripped:
            return ""
        return stripped.rsplit("\n", maxsplit=1)[-1]
