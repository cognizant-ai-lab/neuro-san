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

"""Traffic runner — fires concurrent requests via a thread pool."""

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

from tests.load_tests.config import RequestResult
from tests.load_tests.config import SharedRef
from tests.load_tests.config import STATUS_CREATED
from tests.load_tests.config import STATUS_FAILED
from tests.load_tests.config import STATUS_KILLED
from tests.load_tests.config import STATUS_TIMEOUT
from tests.load_tests.config import THREAD_JOIN_TIMEOUT
from tests.load_tests.cost_estimator import CostEstimator
from tests.load_tests.monitoring.heartbeat import Heartbeat
from tests.load_tests.traffic.cli_builder import CliBuilder
from tests.load_tests.traffic.process_monitor import ProcessMonitor

logger = logging.getLogger(__name__)


class TrafficRunner:
    """Fires concurrent requests via a thread pool and collects results.

    Holds the parsed CLI args and the agent profile so that callers
    do not need to thread them through every method.
    """

    def __init__(self, args, profile) -> None:
        self._args = args
        self._profile = profile

    # pylint: disable=too-many-locals
    def run_one(self, request_id, global_request_id,
                output_dir=None) -> RequestResult:
        """Execute a single request with idle-timeout detection.

        Returns a result dict with status, elapsed, prompt, and parsed fields.
        """
        prompt = self._profile.get_prompt(
            global_request_id, same_prompt=self._args.same_prompt,
        )
        prompt_file = CliBuilder.write_prompt_file(global_request_id, prompt)

        start = time.time()
        status, stdout, stderr, returncode = (
            ProcessMonitor.execute_with_idle_detection(
                CliBuilder.build_cli_command(
                    self._args.host, self._args.port,
                    self._args.agent, prompt_file,
                    include_tokens=self._args.include_tokens,
                ),
                self._args.timeout, self._args.idle_timeout,
            )
        )
        elapsed = time.time() - start

        parsed_fields: Dict[str, str] = {
            field: CliBuilder.parse_stdout_field(stdout, field)
            for field in self._profile.success_fields
        }

        self._save_request_output(
            output_dir, request_id, stdout, stderr,
        )

        status, failure_reason = self._validate_result(
            status, returncode, stdout, parsed_fields,
        )
        self._log_request_result(
            request_id, status, elapsed,
            parsed_fields=parsed_fields,
            failure_reason=failure_reason,
            stderr=stderr,
        )
        CliBuilder.cleanup_prompt_file(prompt_file)

        result = {
            "request_id": f"request-{request_id}",
            "status": status,
            "elapsed": elapsed,
            "prompt": prompt,
            "error": (
                CliBuilder.last_stderr_line(stderr)
                if status != STATUS_CREATED else None
            ),
        }
        result.update(parsed_fields)
        if self._args.include_tokens:
            self._attach_token_data(result, stdout)
        return result

    def _validate_result(self, status, returncode, stdout,
                         parsed_fields,
                         ) -> Tuple[str, Optional[str]]:
        """Determine final status and failure reason for a request."""
        failure_reason = None
        if status in (STATUS_TIMEOUT, STATUS_KILLED):
            return status, failure_reason
        if self._profile.success_fields:
            if self._args.skip_reservation_check:
                required = [
                    f for f in self._profile.success_fields
                    if f != "reservation_id"
                ]
            else:
                required = self._profile.success_fields
            passed = returncode == 0 and all(
                parsed_fields.get(f) for f in required
            )
        else:
            passed = returncode == 0
        if passed and not stdout.strip():
            passed = False
            failure_reason = "empty response from agent"
        status = STATUS_CREATED if passed else STATUS_FAILED
        if status == STATUS_FAILED and not failure_reason:
            failure_reason = self._diagnose_failure(
                returncode, parsed_fields,
            )
        return status, failure_reason

    @staticmethod
    def _attach_token_data(result, stdout) -> None:
        """Parse token accounting from stdout and attach to result."""
        token_data = CliBuilder.parse_token_accounting(stdout)
        if not token_data:
            return
        model = TrafficRunner._extract_model(
            token_data.get("models", {}),
        )
        prompt_tok = token_data.get("prompt_tokens", 0)
        completion_tok = token_data.get("completion_tokens", 0)
        result.update({
            "total_tokens": token_data.get("total_tokens", 0),
            "prompt_tokens": prompt_tok,
            "completion_tokens": completion_tok,
            "llm_calls": token_data.get("successful_requests", 0),
            "model": model,
            "cost_usd": CostEstimator.estimate(
                prompt_tok, completion_tok, model,
            ),
        })

    @staticmethod
    def _extract_model(models_dict) -> str:
        """Extract the specific model name from the nested models dict.

        Token Accounting returns: {"openai": {"gpt-4o-mini": {...}}}.
        This traverses provider -> model to return "gpt-4o-mini".
        """
        for provider_models in models_dict.values():
            if isinstance(provider_models, dict):
                for model_name in provider_models:
                    return model_name
        return "unknown"

    # pylint: disable=too-many-locals,too-many-arguments
    def run_stage(self, num_requests,
                  max_workers, global_offset, *,
                  server_proc=None, output_dir=None
                  ) -> Tuple[float, List[RequestResult], SharedRef]:
        """Fire num_requests concurrent requests using a thread pool."""

        results_list: List[RequestResult] = []
        peak_threads_ref = SharedRef()
        start = time.time()
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [
                pool.submit(
                    self.run_one,
                    i + 1, global_offset + i,
                    output_dir,
                )
                for i in range(num_requests)
            ]
            heartbeat_stop = threading.Event()
            hb = Heartbeat(server_proc)
            heartbeat_thread = threading.Thread(
                target=hb.progress_heartbeat,
                args=(futures, num_requests, start,
                      heartbeat_stop),
                kwargs={
                    "peak_threads_ref": peak_threads_ref,
                },
                daemon=True,
            )
            heartbeat_thread.start()
            for future in futures:
                results_list.append(future.result())
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=THREAD_JOIN_TIMEOUT)
        total_time = time.time() - start
        return total_time, results_list, peak_threads_ref

    def _diagnose_failure(self, returncode, parsed_fields) -> str:
        """Return a human-readable reason why a request was marked FAILED."""
        reasons = []
        if returncode != 0:
            reasons.append(f"non-zero exit code ({returncode})")
        for field in self._profile.success_fields:
            if field == "reservation_id" and self._args.skip_reservation_check:
                continue
            if not parsed_fields.get(field):
                reasons.append(f"missing {field}")
        return "; ".join(reasons) if reasons else "unknown"

    def _log_request_result(self, request_id, status, elapsed, *,
                            parsed_fields, failure_reason,
                            stderr) -> None:
        """Log the result of a single request."""
        logger.info("Request %s: %s (%.2fs)", request_id, status, elapsed)
        for field, value in parsed_fields.items():
            if field == "reservation_id" and self._args.skip_reservation_check:
                logger.info("  %s: skipped", field)
            else:
                logger.info("  %s: %s", field, value or "")
        if failure_reason:
            logger.info("  reason: %s", failure_reason)
        if status in (STATUS_FAILED, STATUS_TIMEOUT, STATUS_KILLED):
            logger.info("  stderr: %s", CliBuilder.last_stderr_line(stderr))

    @staticmethod
    def log_token_summary(results) -> None:
        """Log token usage for each request after token data is attached."""
        has_tokens = any(r.get("total_tokens") for r in results)
        if not has_tokens:
            return
        for result in results:
            total = result.get("total_tokens", 0)
            if not total:
                continue
            prompt_tok = result.get("prompt_tokens", 0)
            comp_tok = result.get("completion_tokens", 0)
            llm_calls = result.get("llm_calls", 0)
            model = result.get("model", "unknown")
            rid = result.get("request_id", "?")
            logger.info(
                "  %s: %s tokens (%s prompt + %s completion), "
                "%s LLM call(s), model=%s",
                rid, f"{total:,}",
                f"{prompt_tok:,}",
                f"{comp_tok:,}",
                llm_calls, model,
            )

    @staticmethod
    def _save_request_output(
            output_dir, request_id, stdout, stderr,
    ) -> None:
        """Save raw CLI stdout/stderr for every request."""
        if not output_dir:
            return
        requests_dir = os.path.join(output_dir, "requests")
        os.makedirs(requests_dir, exist_ok=True)
        stdout_path = os.path.join(
            requests_dir,
            f"request_{request_id}_stdout.txt",
        )
        with open(stdout_path, "w", encoding="utf-8") as fh:
            fh.write(stdout)
        if stderr and stderr.strip():
            stderr_path = os.path.join(
                requests_dir,
                f"request_{request_id}_stderr.txt",
            )
            with open(stderr_path, "w", encoding="utf-8") as fh:
                fh.write(stderr)
