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

# Whole sys module: sys.stdout is looked up on each write, so a swapped stdout is used.
import sys
from argparse import Namespace
from json import dumps
from logging import Logger
from logging import getLogger
from os import makedirs
from os.path import join
from threading import Lock
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from neuro_san.message.processors.basic_message_processor import BasicMessageProcessor

from tests.load_tests.load_test_constants import LoadTestConstants
from tests.load_tests.monitoring.progress_log_writer import ProgressLogWriter
from tests.load_tests.cost_estimator import CostEstimator
from tests.load_tests.reporting.formatters import Formatters
from tests.load_tests.reporting.sly_data_flattener import SlyDataFlattener
from tests.load_tests.traffic.agent_request_result import AgentRequestResult
from tests.load_tests.traffic.output_parser import OutputParser
from tests.load_tests.traffic.request_status_policy import RequestStatusPolicy


class RequestRecorder:
    """
    Records the result of each request TrafficRunner runs.

    Saves the response and error text under requests/, writes a successful request's line to
    progress.log or logs a failed one to the console, and adds the sly_data fields and token
    accounting to the result. Request worker threads share one recorder, so the count of logged
    failures is guarded by a lock.
    """

    def __init__(self, args: Namespace) -> None:
        """
        Constructor.

        :param args: Parsed load-test command line; include_tokens is read at each request,
            since LoadTestCli sets it after the runner is created
        """
        self.logger: Logger = getLogger(self.__class__.__name__)
        self._args: Namespace = args
        self._failure_log_lock: Lock = Lock()
        self._failures_logged: int = 0

    def record_request(self, request_id: int, output_dir: Optional[str],
                       request_result: AgentRequestResult, result: Dict[str, Any]) -> None:
        """
        Save the request output, log the result and add parsed fields and tokens to it.

        :param request_id: Request number within the current stage
        :param output_dir: Directory for per-request output files, or None
        :param request_result: What AgentRequestExecutor returned for the request
        :param result: The request result, updated in place
        """
        processor: Optional[BasicMessageProcessor] = request_result.get_processor()
        response_text: str = request_result.get_response_text()
        token_data: Dict[str, Any] = request_result.get_token_accounting()
        parsed_fields: Dict[str, str] = {}
        if processor is not None:
            sly_data: Dict[str, Any] = processor.get_sly_data()
            parsed_fields = SlyDataFlattener.flatten_string_fields(sly_data)

        # A traceback goes to stderr instead of being saved as the agent's answer.
        stderr: str = ""
        stdout: str = self._http_saved_stdout(response_text, token_data)
        request_status: str = request_result.get_status()
        if RequestStatusPolicy.is_traceback(request_status, response_text):
            stderr = response_text
            stdout = ""

        RequestRecorder._save_request_output(output_dir, request_id, stdout, stderr)

        status: str = result.get("status")
        if output_dir and not RequestStatusPolicy.is_failure(status):
            elapsed_seconds: float = result.get("elapsed")
            RequestRecorder._write_result_to_file(output_dir, request_id, status, elapsed_seconds,
                                                  parsed_fields=parsed_fields)
        else:
            self._log_request_result(request_id, result, parsed_fields=parsed_fields, stderr=stderr)

        result.update(parsed_fields)
        if token_data:
            RequestRecorder._attach_http_token_data(result, token_data)

    def _http_saved_stdout(self, response_text: str, token_data: Optional[Dict[str, Any]]) -> str:
        """
        Join the final answer and the Token Accounting JSON for the saved per-request file.

        :param response_text: Final answer text of the request
        :param token_data: Token Accounting dict from the response, or None
        :return: Text to save as the request's stdout
        """
        saved: str = response_text or ""
        if self._args.include_tokens and token_data:
            token_json: str = dumps(token_data, indent=2)
            saved += "\n\nToken Accounting:\n" + token_json + "\n"
        return saved

    @staticmethod
    def _attach_http_token_data(result: Dict[str, Any], token_data: Optional[Dict[str, Any]]) -> None:
        """
        Attach token accounting from the HTTP response to the result.

        :param result: Request result to update in place
        :param token_data: Token Accounting dict from the response, or None
        """
        if not token_data:
            return
        models_dict: Dict[str, Any] = token_data.get("models", {})
        model: str = RequestRecorder._extract_model(models_dict)
        all_models: List[str] = RequestRecorder._extract_all_models(models_dict)
        prompt_tokens: int = token_data.get("prompt_tokens", 0)
        completion_tokens: int = token_data.get("completion_tokens", 0)
        total_tokens: int = token_data.get("total_tokens", 0)
        llm_calls: int = token_data.get("successful_requests", 0)
        cost_usd: float = CostEstimator.estimate(prompt_tokens, completion_tokens, model)
        token_fields: Dict[str, Any] = {
            "total_tokens": total_tokens,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "llm_calls": llm_calls,
            "model": model,
            "all_models": all_models,
            "cost_usd": cost_usd,
        }
        result.update(token_fields)

    @staticmethod
    def _extract_model(models_dict: Dict[str, Any]) -> str:
        """
        Extract the specific model name from the nested models dict.

        Token Accounting returns: {"openai": {"gpt-4o-mini": {...}}}.
        This traverses provider -> model to return "gpt-4o-mini".

        :param models_dict: Token Accounting "models" dict, provider -> model -> usage
        :return: First model name found, or "unknown"
        """
        # Each provider value is normally a model -> usage dict; anything else is skipped.
        provider_models: Any
        # Return the first model name of the first provider that has one.
        for provider_models in models_dict.values():
            if isinstance(provider_models, dict):
                provider_usage: Dict[str, Any] = provider_models
                model_name: str
                # Return the first model name of this provider.
                for model_name in provider_usage.keys():
                    return model_name
        return "unknown"

    @staticmethod
    def _extract_all_models(models_dict: Dict[str, Any]) -> List[str]:
        """
        Extract all model names from the nested models dict.

        Useful for detecting fallback LLM usage when multiple
        models responded within a single request.

        :param models_dict: Token Accounting "models" dict, provider -> model -> usage
        :return: All model names across all providers
        """
        all_models: List[str] = []
        # Each provider value is normally a model -> usage dict; anything else is skipped.
        provider_models: Any
        # Collect the model names of every provider.
        for provider_models in models_dict.values():
            if isinstance(provider_models, dict):
                provider_usage: Dict[str, Any] = provider_models
                model_name: str
                # Collect each model name of this provider.
                for model_name in provider_usage.keys():
                    all_models.append(model_name)
        return all_models

    def _log_request_result(self, request_id: int, result: Dict[str, Any],
                            parsed_fields: Dict[str, str], stderr: str) -> None:
        """
        Log the result of a single request to the console.

        FAILED/TIMEOUT/KILLED print up to LoadTestConstants.FAILURE_LOG_LIMIT.

        :param request_id: Request number within the current stage
        :param result: The request result, with status, elapsed and failure_reason
        :param parsed_fields: Flattened sly_data string fields of the response
        :param stderr: Error text captured for the request
        """
        status: str = result.get("status")
        elapsed_seconds: float = result.get("elapsed")
        duration_text: str = Formatters.fmt_duration(elapsed_seconds, precision=2)
        failure_reason: Optional[str] = result.get("failure_reason")
        is_failure: bool = RequestStatusPolicy.is_failure(status)
        if is_failure:
            rank: int = 0
            with self._failure_log_lock:
                self._failures_logged += 1
                rank = self._failures_logged
            if rank > LoadTestConstants.FAILURE_LOG_LIMIT:
                return
            if rank == LoadTestConstants.FAILURE_LOG_LIMIT:
                sys.stdout.write("\n")
                sys.stdout.flush()
                self.logger.info("Request %s: %s (%s)", request_id, status, duration_text)
                self.logger.info(
                    "  ... further per-request failures suppressed (see totals below and raw_results.json)")
                return
        sys.stdout.write("\n")
        sys.stdout.flush()
        self.logger.info("Request %s: %s (%s)", request_id, status, duration_text)
        field: str
        value: str
        # Log each parsed sly_data field.
        for field, value in parsed_fields.items():
            field_value: str = value or ""
            self.logger.info("  %s: %s", field, field_value)
        if failure_reason:
            self.logger.info("  reason: %s", failure_reason)
        if is_failure:
            last_error_line: Optional[str] = OutputParser.last_stderr_line(stderr)
            if last_error_line and last_error_line.strip():
                self.logger.info("  stderr: %s", last_error_line)

    @staticmethod
    def _write_result_to_file(output_dir: str, request_id: int, status: str, elapsed_seconds: float,
                              parsed_fields: Dict[str, str]) -> None:
        """
        Append a successful request result to progress.log.

        :param output_dir: Directory holding progress.log
        :param request_id: Request number within the current stage
        :param status: One of the STATUS_* values
        :param elapsed_seconds: Request duration in seconds
        :param parsed_fields: Flattened sly_data string fields of the response
        """
        field_parts: List[str] = []
        key: str
        value: str
        # One "key: value" part per parsed field.
        for key, value in parsed_fields.items():
            field_value: str = value or ""
            field_parts.append(f"{key}: {field_value}")
        fields_text: str = "  ".join(field_parts)
        duration_text: str = Formatters.fmt_duration(elapsed_seconds, precision=2)
        line: str = f"Request {request_id}: {status} ({duration_text})  {fields_text}"
        progress_log_writer: ProgressLogWriter = ProgressLogWriter(output_dir)
        progress_log_writer.write_to_file(line)

    @staticmethod
    def _save_request_output(output_dir: Optional[str], request_id: int, stdout: str, stderr: str) -> None:
        """
        Save the request's response text and error text under output_dir/requests.

        :param output_dir: Run output directory, or None to skip saving
        :param request_id: Request number within the current stage
        :param stdout: Response text to save
        :param stderr: Error text to save; skipped when blank
        """
        if not output_dir:
            return
        requests_dir: str = join(output_dir, LoadTestConstants.REQUESTS_DIR_NAME)
        makedirs(requests_dir, exist_ok=True)
        stdout_path: str = join(requests_dir, f"request_{request_id}_stdout.txt")
        with open(stdout_path, "w", encoding="utf-8") as stdout_file:
            stdout_file.write(stdout)
        if stderr and stderr.strip():
            stderr_path: str = join(requests_dir, f"request_{request_id}_stderr.txt")
            with open(stderr_path, "w", encoding="utf-8") as stderr_file:
                stderr_file.write(stderr)
