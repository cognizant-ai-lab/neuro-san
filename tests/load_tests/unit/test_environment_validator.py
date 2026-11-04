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

from os import environ
from typing import Dict
from typing import List
from unittest import TestCase
from unittest.mock import MagicMock
from unittest.mock import patch

from tests.load_tests.monitoring.resource_monitor import ResourceMonitor
from tests.load_tests.validation.environment_validator import EnvironmentValidator
from tests.load_tests.validation.load_test_abort_error import LoadTestAbortError

GATEWAY_URL: str = "https://litellm.example.com/v1"
MOCK_PID: int = 4321
VALIDATOR_LOGGER_NAME: str = "EnvironmentValidator"


class TestEnvironmentValidator(TestCase):
    """
    Unit tests for EnvironmentValidator().validate_environment().

    Only a running mock_llm_server stops the load test. OPENAI_API_BASE is
    also set for LiteLLM or other gateways, so on its own it is only logged.
    """

    def test_api_base_without_mock_server_does_not_exit(self) -> None:
        """
        OPENAI_API_BASE set and no mock_llm_server: the run goes on and the value is logged.
        """
        with patch.dict(environ, {"OPENAI_API_BASE": GATEWAY_URL}), \
                patch.object(ResourceMonitor, "find_process", return_value=None), \
                self.assertLogs(VALIDATOR_LOGGER_NAME, level="INFO") as logs:
            EnvironmentValidator().validate_environment()
        expected_line: str = f"INFO:{VALIDATOR_LOGGER_NAME}:OPENAI_API_BASE is set: {GATEWAY_URL}"
        self.assertIn(expected_line, logs.output)

    def test_running_mock_server_exits(self) -> None:
        """
        A running mock_llm_server stops the run, with or without OPENAI_API_BASE.
        """
        mock_server_process: MagicMock = MagicMock()
        mock_server_process.get_pid.return_value = MOCK_PID
        with patch.dict(environ, {"OPENAI_API_BASE": GATEWAY_URL}), \
                patch.object(ResourceMonitor, "find_process", return_value=mock_server_process), \
                self.assertLogs(VALIDATOR_LOGGER_NAME, level="ERROR") as logs, \
                self.assertRaises(LoadTestAbortError) as raised:
            EnvironmentValidator().validate_environment()
        exit_code: int = raised.exception.get_exit_code()
        self.assertEqual(exit_code, 1)
        expected_pid_text: str = f"PID {MOCK_PID}"
        self.assertIn(expected_pid_text, logs.output[0])

    def test_no_api_base_and_no_mock_server_does_not_exit(self) -> None:
        """
        Neither OPENAI_API_BASE nor mock_llm_server: the run goes on.
        """
        environment_without_api_base: Dict[str, str] = dict(environ)
        environment_without_api_base.pop("OPENAI_API_BASE", None)
        with patch.dict(environ, environment_without_api_base, clear=True), \
                patch.object(ResourceMonitor, "find_process", return_value=None), \
                self.assertLogs(VALIDATOR_LOGGER_NAME, level="INFO") as logs:
            EnvironmentValidator().validate_environment()
        expected_lines: List[str] = [f"INFO:{VALIDATOR_LOGGER_NAME}:No mock LLM environment detected."]
        self.assertEqual(logs.output, expected_lines)
