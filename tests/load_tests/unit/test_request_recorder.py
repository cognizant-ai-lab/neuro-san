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
from argparse import Namespace
from os.path import exists
from os.path import join
from tempfile import TemporaryDirectory
from typing import Any
from typing import Dict
from typing import List
from unittest import TestCase

from tests.load_tests.load_test_constants import LoadTestConstants
from tests.load_tests.traffic.agent_request_result import AgentRequestResult
from tests.load_tests.traffic.request_recorder import RequestRecorder


class TestRequestRecorder(TestCase):
    """
    Unit tests for RequestRecorder: the files it saves, the progress.log line and the token data it adds.
    """

    STDOUT_FILE_NAME: str = f"request_1{LoadTestConstants.REQUEST_STDOUT_FILE_SUFFIX}"
    STDERR_FILE_NAME: str = f"request_1{LoadTestConstants.REQUEST_STDERR_FILE_SUFFIX}"

    def test_created_request_is_saved_and_written_to_progress_log(self) -> None:
        """
        A CREATED request saves its answer under requests/ and writes its line to progress.log.
        """
        args: Namespace = Namespace(include_tokens=False)
        recorder: RequestRecorder = RequestRecorder(args)
        response: Dict[str, Any] = {"response_text": "hi"}
        request_result: AgentRequestResult = AgentRequestResult(LoadTestConstants.STATUS_CREATED, response)
        result: Dict[str, Any] = TestRequestRecorder._result(LoadTestConstants.STATUS_CREATED)
        stdout_text: str = ""
        progress_text: str = ""
        with TemporaryDirectory() as output_dir:
            recorder.record_request(1, output_dir, request_result, result)
            stdout_path: str = join(output_dir, LoadTestConstants.REQUESTS_DIR_NAME,
                                    TestRequestRecorder.STDOUT_FILE_NAME)
            with open(stdout_path, encoding="utf-8") as stdout_file:
                stdout_text = stdout_file.read()
            stderr_path: str = join(output_dir, LoadTestConstants.REQUESTS_DIR_NAME,
                                    TestRequestRecorder.STDERR_FILE_NAME)
            stderr_saved: bool = exists(stderr_path)
            self.assertFalse(stderr_saved)
            progress_log_path: str = join(output_dir, LoadTestConstants.PROGRESS_LOG_FILE_NAME)
            with open(progress_log_path, encoding="utf-8") as progress_log:
                progress_text = progress_log.read()
        self.assertEqual("hi", stdout_text)
        self.assertIn("Request 1: CREATED", progress_text)

    def test_failed_request_is_logged_to_the_console(self) -> None:
        """
        A FAILED request is logged to the console with its reason.
        """
        args: Namespace = Namespace(include_tokens=False)
        recorder: RequestRecorder = RequestRecorder(args)
        request_result: AgentRequestResult = AgentRequestResult(LoadTestConstants.STATUS_FAILED, {})
        result: Dict[str, Any] = TestRequestRecorder._result(LoadTestConstants.STATUS_FAILED)
        result["failure_reason"] = "empty response from agent"
        with self.assertLogs("RequestRecorder", level="INFO") as captured:
            recorder.record_request(2, None, request_result, result)
        self.assertIn("Request 2: FAILED (1.00s)", captured.output[0])
        self.assertIn("  reason: empty response from agent", captured.output[1])

    def test_token_accounting_is_added_to_the_result(self) -> None:
        """
        The token counts and the first model of the token accounting are added to the result.
        """
        args: Namespace = Namespace(include_tokens=True)
        recorder: RequestRecorder = RequestRecorder(args)
        token_accounting: Dict[str, Any] = {
            "total_tokens": 30,
            "prompt_tokens": 10,
            "completion_tokens": 20,
            "successful_requests": 2,
            "models": {"openai": {"gpt-4o-mini": {}}},
        }
        response: Dict[str, Any] = {"token_accounting": token_accounting}
        request_result: AgentRequestResult = AgentRequestResult(LoadTestConstants.STATUS_CREATED, response)
        result: Dict[str, Any] = TestRequestRecorder._result(LoadTestConstants.STATUS_CREATED)
        with TemporaryDirectory() as output_dir:
            recorder.record_request(1, output_dir, request_result, result)
        total_tokens: int = result.get("total_tokens")
        llm_calls: int = result.get("llm_calls")
        model: str = result.get("model")
        all_models: List[str] = result.get("all_models")
        self.assertEqual(30, total_tokens)
        self.assertEqual(2, llm_calls)
        self.assertEqual("gpt-4o-mini", model)
        self.assertEqual(["gpt-4o-mini"], all_models)

    @staticmethod
    def _result(status: str) -> Dict[str, Any]:
        """
        Return a request result as TrafficRunner.run_one_http() builds it, before it is recorded.

        :param status: One of the STATUS_* values
        :return: The request result
        """
        result: Dict[str, Any] = {
            "status": status,
            "elapsed": 1.0,
            "failure_reason": None,
        }
        return result
