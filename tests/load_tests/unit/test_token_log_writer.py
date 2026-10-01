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


import os
from tempfile import TemporaryDirectory
from typing import Any
from typing import Dict
from typing import List
from unittest import TestCase

from tests.load_tests.reporting.token_log_writer import TokenLogWriter

LOGGER_NAME: str = "tests.load_tests.reporting.token_log_writer"


class TestTokenLogWriter(TestCase):
    """
    TokenLogWriter.log_token_summary() writes per-request detail to
    server_tokens.log when given an output directory, and to the console otherwise.
    """

    @staticmethod
    def _results() -> List[Dict[str, Any]]:
        """
        :return: Two request results with token data and one without
        """
        return [
            {
                "request_id": "request-1", "server_request_id": "srv-1", "status": "CREATED",
                "elapsed": 1.25, "total_tokens": 1500, "prompt_tokens": 1000, "completion_tokens": 500,
                "llm_calls": 2, "model": "gpt-4o-mini",
            },
            {
                "request_id": "request-2", "status": "CREATED", "elapsed": 2.0, "total_tokens": 500,
                "prompt_tokens": 300, "completion_tokens": 200, "llm_calls": 1, "model": "gpt-4o-mini",
                "reporting_agent": "hello_world",
            },
            {"request_id": "request-3", "status": "FAILED", "elapsed": 0.5},
        ]

    @staticmethod
    def _read_token_file(output_dir: str) -> str:
        """
        :param output_dir: Directory that holds server_tokens.log
        :return: Contents of server_tokens.log
        """
        with open(os.path.join(output_dir, "server_tokens.log"), encoding="utf-8") as fh:
            return fh.read()

    def test_no_tokens_writes_and_logs_nothing(self) -> None:
        """
        Without token data there is no server_tokens.log and no console output.
        """
        with TemporaryDirectory() as output_dir:
            with self.assertNoLogs(LOGGER_NAME):
                TokenLogWriter.log_token_summary([{"request_id": "request-1"}], output_dir=output_dir)
            self.assertFalse(os.path.exists(os.path.join(output_dir, "server_tokens.log")))

    def test_output_dir_gets_detail_and_console_gets_totals(self) -> None:
        """
        server_tokens.log holds one block per request with tokens; the console gets the totals.
        """
        network_tokens: List[Dict[str, Any]] = [
            {"request_id": "srv-1", "network": "music_nerd", "llm_calls": 2, "total_tokens": 1500,
             "prompt_tokens": 1000, "completion_tokens": 500},
        ]
        validation_events: List[Dict[str, Any]] = [
            {"request_id": "request-1", "attempts": 2, "fix_cycles": 1, "errors": ["missing key"]},
        ]
        with TemporaryDirectory() as output_dir:
            with self.assertLogs(LOGGER_NAME, level="INFO") as logs:
                TokenLogWriter.log_token_summary(
                    self._results(), output_dir=output_dir,
                    network_tokens=network_tokens, validation_events=validation_events,
                )
            self.assertEqual(
                "request-1: 1,500 tokens, 2 LLM call(s), model=gpt-4o-mini  [1.2s CREATED]\n"
                "  Validation: 2 attempt(s), 1 fix cycle(s)\n"
                "    - missing key\n"
                "  music_nerd: 2 call(s)  1,500 tokens (1,000 prompt / 500 completion)\n"
                "\n"
                "request-2: 500 tokens, 1 LLM call(s), model=gpt-4o-mini, agent=hello_world  [2.0s CREATED]\n"
                "  hello_world: 1 call(s)  500 tokens (300 prompt / 200 completion)\n"
                "\n",
                self._read_token_file(output_dir),
            )
        output: str = "\n".join(logs.output)
        self.assertIn("Total: 2,000 tokens (1,300 prompt + 700 completion)", output)
        self.assertIn("2 requests, avg 1,000 tokens/request", output)

    def test_missing_agent_data_is_noted(self) -> None:
        """
        A request with tokens but no agent data says so in server_tokens.log.
        """
        with TemporaryDirectory() as output_dir:
            with self.assertLogs(LOGGER_NAME, level="INFO"):
                TokenLogWriter.log_token_summary(self._results()[:1], output_dir=output_dir)
            self.assertIn("  (agent data not found in server log)\n", self._read_token_file(output_dir))

    def test_without_output_dir_logs_each_request(self) -> None:
        """
        Without an output directory each request with tokens is logged to the console.
        """
        with self.assertLogs(LOGGER_NAME, level="INFO") as logs:
            TokenLogWriter.log_token_summary(self._results())
        self.assertEqual(2, len(logs.output))
        self.assertIn(
            "request-1: 1,500 tokens (1,000 prompt + 500 completion), 2 LLM call(s), model=gpt-4o-mini",
            logs.output[0],
        )
