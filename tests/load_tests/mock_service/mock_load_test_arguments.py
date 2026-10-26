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

from argparse import ArgumentParser
from argparse import Namespace
from argparse import RawDescriptionHelpFormatter
from logging import Logger
from logging import getLogger
from typing import Dict
from typing import KeysView
from typing import List
from typing import Optional

from tests.load_tests.mock_service.mock_server_manager import MockServerManager
from tests.load_tests.validation.load_test_abort_error import LoadTestAbortError


class MockLoadTestArguments:
    """
    Command-line arguments of the mock LLM load test.

    Parses the flags, then fills in the prompt and sly-data of a known agent from AGENT_PRESETS.
    """

    AGENT_PRESETS: Dict[str, Dict[str, Optional[str]]] = {
        "math_guy": {
            "prompt": "add",
            "sly_data": '{"x": 3, "y": 5}',
        },
        "hello_world": {
            "prompt": "Greet developers that wrote their very first program",
            "sly_data": None,
        },
        "chat_mock_llm_echo": {
            "prompt": "Hello, testing the mock LLM",
            "sly_data": None,
        },
    }

    def __init__(self, usage_text: str) -> None:
        """
        Initialize the argument parser state.

        :param usage_text: Usage examples that --help prints after the flags
        """
        self.logger: Logger = getLogger(self.__class__.__name__)
        self._usage_text: str = usage_text
        self._args: Optional[Namespace] = None

    def parse_args(self) -> Namespace:
        """
        Parse command-line arguments for load test configuration, then apply the agent presets.

        :return: The parsed command-line arguments
        :raises LoadTestAbortError: With exit code 1 when the agent has no preset and --prompt is missing
        """
        parser: ArgumentParser = ArgumentParser(
            description="Load-test neuro-san server with resource leak detection.",
            formatter_class=RawDescriptionHelpFormatter,
            epilog=self._usage_text,
        )
        parser.add_argument(
            "--agent",
            type=str,
            default="math_guy",
            help="Agent network name to test (default: %(default)s)",
        )
        parser.add_argument("--num-requests", type=int, default=10,
                            help="Number of requests per round (default: %(default)s)")
        parser.add_argument("--max-workers", type=int, default=10, help="Max concurrent workers (default: %(default)s)")
        parser.add_argument("--num-rounds", type=int, default=5, help="Number of rounds to run (default: %(default)s)")
        parser.add_argument(
            "--prompt",
            type=str,
            default=None,
            help="Prompt text to send to the agent. Auto-filled from preset if agent is known.",
        )
        parser.add_argument(
            "--sly-data",
            type=str,
            default=None,
            help="JSON sly_data string. Auto-filled from preset if agent is known. Use --no-sly-data to omit.",
        )
        parser.add_argument(
            "--no-sly-data",
            action="store_true",
            default=False,
            help="Do not pass --sly_data to agent_cli",
        )
        parser.add_argument("--host", type=str, default=MockServerManager.LOCALHOST,
                            help="Neuro-san server host (default: %(default)s)")
        parser.add_argument("--port", type=int, default=8080, help="Neuro-san server port (default: %(default)s)")
        parser.add_argument(
            "--settle-time",
            dest="settle_time_seconds",
            metavar="SETTLE_TIME",
            type=int,
            default=10,
            help="Seconds to wait after each round for cleanup (default: %(default)s)",
        )
        parser.add_argument(
            "--auto-start",
            action="store_true",
            default=False,
            help="Auto-start mock LLM and neuro-san servers as subprocesses",
        )
        parser.add_argument(
            "--mock-port",
            type=int,
            default=MockServerManager.DEFAULT_MOCK_PORT,
            help="Mock LLM server port (default: %(default)s). Used with --auto-start.",
        )
        self._args = parser.parse_args()
        self._apply_presets()
        return self._args

    def _apply_presets(self) -> None:
        """
        Fill in prompt and sly-data from AGENT_PRESETS when the user has not
        provided them explicitly. Abort if the agent is unknown and --prompt
        is missing.

        :raises LoadTestAbortError: With exit code 1 when the agent has no preset and --prompt is missing
        """
        preset: Optional[Dict[str, Optional[str]]] = MockLoadTestArguments.AGENT_PRESETS.get(self._args.agent)

        if self._args.prompt is None:
            if preset is None:
                preset_names: KeysView[str] = MockLoadTestArguments.AGENT_PRESETS.keys()
                agent_names: List[str] = sorted(preset_names)
                known_agents: str = ", ".join(agent_names)
                self.logger.error(
                    """No preset for agent '%s'. Please provide --prompt explicitly.
Known presets: %s""",
                    self._args.agent, known_agents,
                )
                raise LoadTestAbortError(1)
            self._args.prompt = preset.get("prompt")

        if self._args.sly_data is None and not self._args.no_sly_data:
            preset_sly_data: Optional[str] = None
            if preset is not None:
                preset_sly_data = preset.get("sly_data")
            if preset_sly_data is not None:
                self._args.sly_data = preset_sly_data
            else:
                self._args.no_sly_data = True
