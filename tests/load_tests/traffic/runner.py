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
from concurrent.futures import as_completed
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

        try:
            start = time.time()
            status, stdout, stderr, returncode, ttft = (
                ProcessMonitor.execute_with_idle_detection(
                    CliBuilder.build_cli_command(
                        self._args.host, self._args.port,
                        self._args.agent, prompt_file,
                        include_tokens=self._args.include_tokens,
                    ),
                    self._args.request_timeout, self._args.idle_timeout,
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
                output_dir=output_dir,
            )

            result = {
                "request_id": f"request-{request_id}",
                "status": status,
                "elapsed": elapsed,
                "ttft": ttft,
                "start_time": start,
                "end_time": start + elapsed,
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
        finally:
            CliBuilder.cleanup_prompt_file(prompt_file)

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
        if passed:
            matched = self._check_failure_patterns(stdout)
            if matched is not None:
                passed = False
                failure_reason = (
                    f"response matched failure pattern: {matched}"
                )
        status = STATUS_CREATED if passed else STATUS_FAILED
        if status == STATUS_FAILED and not failure_reason:
            failure_reason = self._diagnose_failure(
                returncode, parsed_fields,
            )
        return status, failure_reason

    def _check_failure_patterns(self, stdout) -> Optional[str]:
        """Check stdout against the profile's failure patterns.

        Returns the first matched pattern, or None if no match.
        """
        for pattern in self._profile.failure_patterns:
            if pattern in stdout:
                return pattern
        return None

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
                  server_proc=None, client_proc=None,
                  output_dir=None,
                  stage_timeout=None,
                  ) -> Tuple[
        float, List[RequestResult], SharedRef, SharedRef,
        SharedRef, bool,
    ]:
        """Fire num_requests concurrent requests using a thread pool.

        Returns (elapsed, results, peak_threads_ref,
        peak_client_rss_ref, peak_server_rss_ref, server_died).
        """
        results_list: List[RequestResult] = []
        peak_threads_ref = SharedRef()
        peak_client_rss_ref = SharedRef()
        peak_server_rss_ref = SharedRef()
        server_dead_event = threading.Event()
        start = time.time()
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            heartbeat_stop = threading.Event()
            heartbeat_ready = threading.Event()
            fires_done_event = threading.Event()
            futures_ref: list = []
            hb = Heartbeat(server_proc, client_proc, output_dir)
            heartbeat_thread = threading.Thread(
                target=hb.progress_heartbeat,
                args=(futures_ref, num_requests, start,
                      heartbeat_stop),
                kwargs={
                    "ready_event": heartbeat_ready,
                    "fires_done_event": fires_done_event,
                    "peak_threads_ref": peak_threads_ref,
                    "peak_client_rss_ref": peak_client_rss_ref,
                    "peak_server_rss_ref": peak_server_rss_ref,
                    "server_dead_event": server_dead_event,
                },
                daemon=True,
            )
            heartbeat_thread.start()
            heartbeat_ready.wait()
            futures_ref.extend(
                pool.submit(
                    self.run_one,
                    i + 1, global_offset + i,
                    output_dir,
                )
                for i in range(num_requests)
            )
            fires_done_event.set()
            killed_count = self._collect_with_timeout(
                futures_ref, results_list,
                start=start, stage_timeout=stage_timeout,
            )
            if killed_count:
                logger.warning(
                    "  Stage timeout (%ss) reached — "
                    "%s request(s) killed.",
                    stage_timeout, killed_count,
                )
            heartbeat_stop.set()
            heartbeat_thread.join(timeout=THREAD_JOIN_TIMEOUT)
        total_time = time.time() - start
        return (
            total_time, results_list,
            peak_threads_ref, peak_client_rss_ref,
            peak_server_rss_ref, server_dead_event.is_set(),
        )

    @staticmethod
    def _collect_with_timeout(
            futures, results_list, *,
            start, stage_timeout,
    ) -> int:
        """Collect future results, cancelling stragglers on timeout.

        Returns the number of futures that were killed.
        """
        if stage_timeout is None:
            for fut in futures:
                results_list.append(fut.result())
            return 0

        pending = set(futures)
        killed = 0
        while pending:
            elapsed = time.time() - start
            remaining = max(0, stage_timeout - elapsed)
            if remaining <= 0:
                break
            try:
                for fut in as_completed(pending, timeout=remaining):
                    results_list.append(fut.result())
                    pending.discard(fut)
            except TimeoutError:
                pass

        for fut in pending:
            fut.cancel()
        for fut in pending:
            if fut.cancelled():
                killed += 1
                results_list.append({
                    "request_id": "unknown",
                    "status": STATUS_KILLED,
                    "stdout": "",
                    "stderr": "Killed by --stage-timeout",
                    "returncode": -1,
                    "duration": time.time() - start,
                })
            else:
                results_list.append(fut.result())
        return killed

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
                            stderr, output_dir=None) -> None:
        """Log the result of a single request.

        CREATED results go to progress.log when output_dir is set.
        FAILED/TIMEOUT/KILLED always print to console.
        """
        is_failure = status in (
            STATUS_FAILED, STATUS_TIMEOUT, STATUS_KILLED,
        )
        if output_dir and not is_failure:
            self._write_result_to_file(
                output_dir, request_id, status, elapsed,
                parsed_fields=parsed_fields,
            )
            return
        logger.info("Request %s: %s (%.2fs)", request_id, status, elapsed)
        for field, value in parsed_fields.items():
            if field == "reservation_id" and self._args.skip_reservation_check:
                logger.info("  %s: skipped", field)
            else:
                logger.info("  %s: %s", field, value or "")
        if failure_reason:
            logger.info("  reason: %s", failure_reason)
        if is_failure:
            logger.info("  stderr: %s", CliBuilder.last_stderr_line(stderr))

    @staticmethod
    def _write_result_to_file(output_dir, request_id, status,
                              elapsed, *, parsed_fields) -> None:
        """Append a successful request result to progress.log."""
        path = os.path.join(output_dir, "progress.log")
        fields_str = "  ".join(
            f"{k}: {v or ''}" for k, v in parsed_fields.items()
        )
        line = (
            f"Request {request_id}: {status} ({elapsed:.2f}s)"
            f"  {fields_str}\n"
        )
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line)

    @staticmethod
    def log_token_summary(
            results, *, output_dir=None,
            network_tokens=None,
            validation_events=None,
    ) -> None:
        """Log token usage summary to console, detail to file.

        When output_dir is provided, per-request lines go to
        server_tokens.log and only totals appear on the console.
        Without output_dir, per-request lines go to the console.
        """
        has_tokens = any(r.get("total_tokens") for r in results)
        if not has_tokens:
            return
        if output_dir:
            TrafficRunner._write_token_file(
                results, output_dir,
                network_tokens=network_tokens,
                validation_events=validation_events,
            )
            TrafficRunner._log_token_totals(results)
        else:
            TrafficRunner._log_token_per_request(results)

    @staticmethod
    def _log_token_per_request(results) -> None:
        """Log per-request token lines to the console."""
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
    def _write_token_file(
            results, output_dir, *,
            network_tokens=None,
            validation_events=None,
    ) -> None:
        """Write per-request token detail to server_tokens.log."""
        by_request = TrafficRunner._group_network_tokens(
            network_tokens,
        )
        by_validation = TrafficRunner._group_validation_events(
            validation_events,
        )
        path = os.path.join(output_dir, "server_tokens.log")
        with open(path, "w", encoding="utf-8") as fh:
            for result in results:
                total = result.get("total_tokens", 0)
                if not total:
                    continue
                TrafficRunner._write_token_request(
                    fh, result, by_request,
                    by_validation,
                )
        logger.info("  Detail:  %s", path)

    @staticmethod
    def _group_network_tokens(network_tokens):
        """Group network token entries by request_id."""
        by_request = {}
        for entry in (network_tokens or []):
            rid = entry.get("request_id", "")
            by_request.setdefault(rid, []).append(entry)
        return by_request

    @staticmethod
    def _group_validation_events(validation_events):
        """Index validation events by request_id."""
        by_request = {}
        for event in (validation_events or []):
            rid = event.get("request_id", "")
            by_request[rid] = event
        return by_request

    @staticmethod
    def _write_token_request(
            fh, result, by_request, by_validation,
    ) -> None:
        """Write one request's token line with agent breakdown."""
        rid = result.get("request_id", "?")
        total = result.get("total_tokens", 0)
        llm_calls = result.get("llm_calls", 0)
        model = result.get("model", "unknown")
        elapsed = result.get("elapsed", 0)
        status = result.get("status", "?")
        fh.write(
            f"{rid}: {total:,} tokens, "
            f"{llm_calls} LLM call(s), "
            f"model={model}"
            f"  [{elapsed:.1f}s {status}]\n"
        )
        TrafficRunner._write_validation_detail(
            fh, rid, by_validation,
        )
        agents = by_request.get(rid, [])
        for agent in agents:
            net = agent.get("network", "?")
            a_calls = agent.get("llm_calls", 0)
            a_total = agent.get("total_tokens", 0)
            a_prompt = agent.get("prompt_tokens", 0)
            a_comp = agent.get("completion_tokens", 0)
            fh.write(
                f"  {net}: {a_calls} call(s)"
                f"  {a_total:,} tokens"
                f" ({a_prompt:,} prompt"
                f" / {a_comp:,} completion)\n"
            )
        if agents or rid in by_validation:
            fh.write("\n")

    @staticmethod
    def _write_validation_detail(fh, rid, by_validation):
        """Write per-request validation retry detail."""
        event = by_validation.get(rid)
        if not event:
            return
        attempts = event.get("attempts", 0)
        fix_cycles = event.get("fix_cycles", 0)
        fh.write(
            f"  Validation: {attempts} attempt(s),"
            f" {fix_cycles} fix cycle(s)\n"
        )
        errors = event.get("errors", [])
        for err in errors:
            fh.write(f"    - {err}\n")

    @staticmethod
    def _log_token_totals(results) -> None:
        """Log aggregate token totals to the console."""
        total_tok = 0
        total_prompt = 0
        total_comp = 0
        count = 0
        for result in results:
            tok = result.get("total_tokens", 0)
            if not tok:
                continue
            total_tok += tok
            total_prompt += result.get("prompt_tokens", 0)
            total_comp += result.get("completion_tokens", 0)
            count += 1
        if count == 0:
            return
        avg = total_tok // count
        logger.info(
            "  Total: %s tokens (%s prompt + %s completion)",
            f"{total_tok:,}", f"{total_prompt:,}",
            f"{total_comp:,}",
        )
        logger.info(
            "  %s requests, avg %s tokens/request",
            count, f"{avg:,}",
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
