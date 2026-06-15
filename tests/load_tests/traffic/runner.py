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
from typing import Any
from typing import Dict
from typing import List

from tests.load_tests.config import STATUS_CREATED
from tests.load_tests.config import STATUS_FAILED
from tests.load_tests.config import STATUS_KILLED
from tests.load_tests.config import STATUS_TIMEOUT
from tests.load_tests.config import estimate_cost
from tests.load_tests.traffic.cli_builder import CliBuilder
from tests.load_tests.traffic.process_monitor import ProcessMonitor

logger = logging.getLogger(__name__)


class TrafficRunner:
    """Fires concurrent requests via a thread pool and collects results."""

    _output_log_dir = None

    # pylint: disable=too-many-locals
    @staticmethod
    def run_one(args, profile, request_id, global_request_id,
                output_dir=None):
        """Execute a single request with idle-timeout detection.

        Returns a result dict with status, elapsed, prompt, and parsed fields.
        """
        prompt = profile.get_prompt(
            global_request_id, same_prompt=args.same_prompt,
        )
        prompt_file = CliBuilder.write_prompt_file(global_request_id, prompt)

        include_tokens = getattr(args, "include_tokens", False)
        cmd = CliBuilder.build_cli_command(
            args.host, args.port, args.agent, prompt_file,
            include_tokens=include_tokens,
        )
        start = time.time()
        status, stdout, stderr, returncode = (
            ProcessMonitor.execute_with_idle_detection(
                cmd, args.timeout, args.idle_timeout,
            )
        )
        elapsed = time.time() - start

        parsed_fields: Dict[str, str] = {}
        for field in profile.success_fields:
            parsed_fields[field] = CliBuilder.parse_stdout_field(stdout, field)

        TrafficRunner._save_request_output(
            output_dir, request_id, stdout, stderr,
        )

        failure_reason = None
        if status not in (STATUS_TIMEOUT, STATUS_KILLED):
            if profile.success_fields:
                skip_reservation = getattr(
                    args, "skip_reservation_check", False,
                )
                if skip_reservation:
                    required = [
                        f for f in profile.success_fields
                        if f != "reservation_id"
                    ]
                else:
                    required = profile.success_fields
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
                failure_reason = TrafficRunner._diagnose_failure(
                    returncode, parsed_fields, profile.success_fields,
                    getattr(args, "skip_reservation_check", False),
                )

        TrafficRunner._log_request_result(
            request_id, status, elapsed, parsed_fields, failure_reason,
            stderr, getattr(args, "skip_reservation_check", False),
        )
        CliBuilder.cleanup_prompt_file(prompt_file)
        error_line = (
            CliBuilder.last_stderr_line(stderr)
            if status != STATUS_CREATED else None
        )

        result = {
            "request_id": f"request-{request_id}",
            "status": status,
            "elapsed": elapsed,
            "prompt": prompt,
            "error": error_line,
        }
        result.update(parsed_fields)

        if include_tokens:
            token_data = CliBuilder.parse_token_accounting(stdout)
            if token_data:
                result["total_tokens"] = token_data.get(
                    "total_tokens", 0,
                )
                result["prompt_tokens"] = token_data.get(
                    "prompt_tokens", 0,
                )
                result["completion_tokens"] = token_data.get(
                    "completion_tokens", 0,
                )
                result["llm_calls"] = token_data.get(
                    "successful_requests", 0,
                )
                models = token_data.get("models", {})
                result["model"] = (
                    next(iter(models)) if models else "unknown"
                )
                result["cost_usd"] = estimate_cost(
                    result["prompt_tokens"],
                    result["completion_tokens"],
                    result["model"],
                )

        return result

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    # pylint: disable=too-many-locals
    @staticmethod
    def run_stage(args, profile, num_requests, max_workers, global_offset,
                  server_proc=None, output_dir=None):
        """Fire num_requests concurrent requests using a thread pool."""
        # Lazy import to avoid circular dependency: heartbeat -> runner
        from tests.load_tests.monitoring.heartbeat import Heartbeat  # pylint: disable=import-outside-toplevel

        results_list: List[Dict[str, Any]] = []
        peak_threads_result: Dict[str, int] = {}
        start = time.time()
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [
                pool.submit(
                    TrafficRunner.run_one, args, profile,
                    i + 1, global_offset + i,
                    output_dir,
                )
                for i in range(num_requests)
            ]
            heartbeat_stop = threading.Event()
            heartbeat = threading.Thread(
                target=Heartbeat.progress_heartbeat,
                args=(futures, num_requests, start,
                      heartbeat_stop, server_proc,
                      peak_threads_result),
                daemon=True,
            )
            heartbeat.start()
            for future in futures:
                results_list.append(future.result())
            heartbeat_stop.set()
            heartbeat.join(timeout=2)
        total_time = time.time() - start
        return total_time, results_list, peak_threads_result

    @staticmethod
    def _diagnose_failure(returncode, parsed_fields, success_fields,
                          skip_reservation_check):
        """Return a human-readable reason why a request was marked FAILED."""
        reasons = []
        if returncode != 0:
            reasons.append(f"non-zero exit code ({returncode})")
        for field in success_fields:
            if field == "reservation_id" and skip_reservation_check:
                continue
            if not parsed_fields.get(field):
                reasons.append(f"missing {field}")
        return "; ".join(reasons) if reasons else "unknown"

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    @staticmethod
    def _log_request_result(request_id, status, elapsed, parsed_fields,
                            failure_reason, stderr, skip_reservation_check):
        """Log the result of a single request."""
        logger.info("Request %s: %s (%.2fs)", request_id, status, elapsed)
        for field, value in parsed_fields.items():
            if field == "reservation_id" and skip_reservation_check:
                logger.info("  %s: skipped", field)
            else:
                logger.info("  %s: %s", field, value or "")
        if failure_reason:
            logger.info("  reason: %s", failure_reason)
        if status in (STATUS_FAILED, STATUS_TIMEOUT, STATUS_KILLED):
            logger.info("  stderr: %s", CliBuilder.last_stderr_line(stderr))

    @staticmethod
    def log_token_summary(results):
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
                rid, f"{total:,}", f"{prompt_tok:,}", f"{comp_tok:,}",
                llm_calls, model,
            )

    @staticmethod
    def _save_request_output(output_dir, request_id, stdout, stderr):
        """Save raw CLI stdout/stderr for every request."""
        if not output_dir:
            return
        if TrafficRunner._output_log_dir is None:
            TrafficRunner._output_log_dir = os.path.join(
                output_dir, "requests",
            )
            os.makedirs(TrafficRunner._output_log_dir, exist_ok=True)
        stdout_path = os.path.join(
            TrafficRunner._output_log_dir,
            f"request_{request_id}_stdout.txt",
        )
        with open(stdout_path, "w", encoding="utf-8") as fh:
            fh.write(stdout)
        if stderr and stderr.strip():
            stderr_path = os.path.join(
                TrafficRunner._output_log_dir,
                f"request_{request_id}_stderr.txt",
            )
            with open(stderr_path, "w", encoding="utf-8") as fh:
                fh.write(stderr)
