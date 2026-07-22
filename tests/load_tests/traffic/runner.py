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

"""Traffic runner — fires concurrent requests via a thread pool."""

import json
import logging
import os
import re
import sys
import threading
import time
from concurrent.futures import as_completed
from concurrent.futures import CancelledError
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

from tests.load_tests.config import FAILURE_LOG_LIMIT
from tests.load_tests.config import Formatters
from tests.load_tests.config import RequestResult
from tests.load_tests.config import SharedRef
from tests.load_tests.config import STATUS_CREATED
from tests.load_tests.config import STATUS_FAILED
from tests.load_tests.config import STATUS_KILLED
from tests.load_tests.config import STATUS_TIMEOUT
from tests.load_tests.config import POLL_INTERVAL_SECONDS
from tests.load_tests.config import THREAD_JOIN_TIMEOUT
from tests.load_tests.cost_estimator import CostEstimator
from tests.load_tests.monitoring.heartbeat import Heartbeat
from tests.load_tests.traffic.cli_builder import CliBuilder
from tests.load_tests.traffic.http_client import HttpClient
from tests.load_tests.traffic.process_monitor import ProcessMonitor

logger = logging.getLogger(__name__)

# Grace period after Ctrl-C for in-flight requests to wind down before
# they are recorded as KILLED.  Sized above the subprocess poll interval
# so killed subprocess requests have time to resolve.
INTERRUPT_GRACE_SECONDS = 2 * POLL_INTERVAL_SECONDS + 2.0


class TrafficRunner:
    """Fires concurrent requests via a thread pool and collects results.

    Holds the parsed CLI args and the agent profile so that callers
    do not need to thread them through every method.
    """

    def __init__(self, args, profile) -> None:
        self._args = args
        self._profile = profile
        self._failure_log_lock = threading.Lock()
        self._failures_logged = 0

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def _run_one_tracked(self, request_id, global_request_id,
                         output_dir, failed_ref,
                         cancel_event=None) -> RequestResult:
        """Run one request and increment failed_ref on failure."""
        if getattr(self._args, "http_client", False):
            result = self.run_one_http(
                request_id, global_request_id, output_dir,
            )
        else:
            result = self.run_one(
                request_id, global_request_id, output_dir,
                cancel_event=cancel_event,
            )
        if result.get("status") != STATUS_CREATED:
            failed_ref.value = (failed_ref.value or 0) + 1
        return result

    # pylint: disable=too-many-locals
    def run_one(self, request_id, global_request_id,
                output_dir=None, cancel_event=None) -> RequestResult:
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
                        use_https=getattr(self._args, "https", False),
                    ),
                    self._args.request_timeout, self._args.idle_timeout,
                    cancel_event,
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
                "failure_reason": failure_reason,
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

    # pylint: disable=too-many-locals
    def run_one_http(self, request_id, global_request_id,
                     output_dir=None) -> RequestResult:
        """Execute a single request via direct HTTP.

        Uses thread-based HTTP POST instead of spawning a
        subprocess, reducing per-request memory from ~96 MB
        to ~1-2 MB.
        """
        prompt = self._profile.get_prompt(
            global_request_id,
            same_prompt=self._args.same_prompt,
        )
        start = time.time()
        status, parsed_fields, response_text, ttft, token_data = (
            HttpClient.execute_request(
                self._args.host, self._args.port,
                self._args.agent, prompt,
                timeout=self._args.request_timeout,
                idle_timeout=self._args.idle_timeout,
                use_https=getattr(self._args, "https", False),
            )
        )
        elapsed = time.time() - start

        # Subprocess mode extracts fields via regex over the
        # entire stdout (answer text + sly_data).  Match that
        # behaviour: for any success field not already found in
        # sly_data, search the answer text with the same regex.
        for field in self._profile.success_fields:
            if not parsed_fields.get(field) and response_text:
                match = re.search(
                    rf'"{field}"\s*:\s*"([^"]+)"',
                    response_text,
                )
                if match:
                    parsed_fields[field] = match.group(1)

        failure_reason = None
        if status == STATUS_CREATED:
            for pattern in self._profile.failure_patterns:
                if pattern in response_text:
                    status = STATUS_FAILED
                    failure_reason = (
                        "response matched failure pattern: "
                        + pattern
                    )
                    break
            if status == STATUS_CREATED:
                if self._args.skip_reservation_check:
                    required = [
                        f for f in self._profile.success_fields
                        if f != "reservation_id"
                    ]
                else:
                    required = self._profile.success_fields
                missing = [
                    f for f in required
                    if not parsed_fields.get(f)
                ]
                if missing:
                    status = STATUS_FAILED
                    failure_reason = (
                        "missing " + ", ".join(missing)
                    )
        elif status == STATUS_FAILED and not response_text:
            failure_reason = "empty response from agent"

        self._save_request_output(
            output_dir, request_id,
            self._http_saved_stdout(response_text, token_data), "",
        )

        self._log_request_result(
            request_id, status, elapsed,
            parsed_fields=parsed_fields,
            failure_reason=failure_reason,
            stderr="",
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
            "failure_reason": failure_reason,
            "error": (
                failure_reason
                if status != STATUS_CREATED else None
            ),
        }
        result.update(parsed_fields)
        if token_data:
            self._attach_http_token_data(result, token_data)
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
                returncode, parsed_fields, stdout,
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
        models_dict = token_data.get("models", {})
        model = TrafficRunner._extract_model(models_dict)
        all_models = TrafficRunner._extract_all_models(
            models_dict,
        )
        prompt_tok = token_data.get("prompt_tokens", 0)
        completion_tok = token_data.get("completion_tokens", 0)
        result.update({
            "total_tokens": token_data.get("total_tokens", 0),
            "prompt_tokens": prompt_tok,
            "completion_tokens": completion_tok,
            "llm_calls": token_data.get("successful_requests", 0),
            "model": model,
            "all_models": all_models,
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

    @staticmethod
    def _extract_all_models(models_dict) -> list:
        """Extract all model names from the nested models dict.

        Returns a list of all model names across all providers,
        useful for detecting fallback LLM usage when multiple
        models responded within a single request.
        """
        all_models = []
        for provider_models in models_dict.values():
            if isinstance(provider_models, dict):
                all_models.extend(provider_models.keys())
        return all_models

    def _http_saved_stdout(self, response_text, token_data) -> str:
        """Final answer plus Token Accounting JSON (agent_cli parity).

        In HTTP mode the client receives the answer and token
        accounting on separate channels; join them so the saved
        per-request file matches subprocess (agent_cli) output.
        """
        saved = response_text or ""
        if self._args.include_tokens and token_data:
            saved += (
                "\n\nToken Accounting:\n"
                + json.dumps(token_data, indent=2)
                + "\n"
            )
        return saved

    @staticmethod
    def _attach_http_token_data(result, token_data) -> None:
        """Attach token accounting from HTTP response to result.

        Same logic as _attach_token_data but accepts the
        token_accounting dict directly instead of parsing from
        stdout.
        """
        if not token_data:
            return
        models_dict = token_data.get("models", {})
        model = TrafficRunner._extract_model(models_dict)
        all_models = TrafficRunner._extract_all_models(
            models_dict,
        )
        prompt_tok = token_data.get("prompt_tokens", 0)
        completion_tok = token_data.get("completion_tokens", 0)
        result.update({
            "total_tokens": token_data.get("total_tokens", 0),
            "prompt_tokens": prompt_tok,
            "completion_tokens": completion_tok,
            "llm_calls": token_data.get(
                "successful_requests", 0,
            ),
            "model": model,
            "all_models": all_models,
            "cost_usd": CostEstimator.estimate(
                prompt_tok, completion_tok, model,
            ),
        })

    # pylint: disable=too-many-locals,too-many-arguments
    def run_stage(self, num_requests,
                  max_workers, global_offset, *,
                  server_proc=None, client_proc=None,
                  output_dir=None,
                  stage_timeout=None,
                  cancel_event=None,
                  log_monitor=None,
                  primary_start_pattern=None,
                  ) -> Tuple[
        float, List[RequestResult], SharedRef, SharedRef,
        SharedRef, SharedRef, SharedRef, bool, bool,
    ]:
        """Fire num_requests concurrent requests using a thread pool.

        Returns (elapsed, results, peak_threads_ref,
        peak_client_rss_ref, peak_server_rss_ref,
        peak_sys_mem_pct_ref, peak_sys_cpu_ref, server_died,
        interrupted).

        When ``cancel_event`` becomes set (Ctrl-C), in-flight
        subprocess requests are killed and the stage returns early
        with whatever completed so far, marking the remainder KILLED.
        """
        results_list: List[RequestResult] = []
        peak_threads_ref = SharedRef()
        peak_client_rss_ref = SharedRef()
        peak_server_rss_ref = SharedRef()
        peak_sys_mem_pct_ref = SharedRef()
        peak_sys_cpu_ref = SharedRef()
        failed_ref = SharedRef()
        failed_ref.value = 0
        server_dead_event = threading.Event()
        start = time.time()
        interrupted = False
        heartbeat_thread = None
        heartbeat_stop = threading.Event()
        # Not using ``with`` so that on Ctrl-C we can shut the pool
        # down without blocking on stalled worker threads (e.g.
        # in-thread HTTP requests that cannot be force-killed).
        pool = ThreadPoolExecutor(max_workers=max_workers)
        try:
            heartbeat_ready = threading.Event()
            fires_done_event = threading.Event()
            futures_ref: list = []
            log_start_pos = (
                log_monitor.read_position()
                if log_monitor is not None else None
            )
            hb = Heartbeat(
                server_proc, client_proc, output_dir,
                log_monitor=log_monitor,
                log_start_pos=log_start_pos,
                primary_start_pattern=primary_start_pattern,
            )
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
                    "peak_sys_mem_pct_ref": peak_sys_mem_pct_ref,
                    "peak_sys_cpu_ref": peak_sys_cpu_ref,
                    "failed_ref": failed_ref,
                    "server_dead_event": server_dead_event,
                },
                daemon=True,
            )
            heartbeat_thread.start()
            heartbeat_ready.wait()
            futures_ref.extend(
                pool.submit(
                    self._run_one_tracked,
                    i + 1, global_offset + i,
                    output_dir, failed_ref, cancel_event,
                )
                for i in range(num_requests)
            )
            fires_done_event.set()
            killed_count, interrupted = self._collect_with_timeout(
                futures_ref, results_list,
                start=start, stage_timeout=stage_timeout,
                cancel_event=cancel_event,
            )
            if killed_count and not interrupted:
                logger.warning(
                    "  Stage timeout (%ss) reached — "
                    "%s request(s) killed.",
                    stage_timeout, killed_count,
                )
            elif interrupted:
                logger.warning(
                    "  Interrupted (Ctrl-C) — %s request(s) still "
                    "in flight were dropped; reporting completed ones.",
                    killed_count,
                )
        finally:
            heartbeat_stop.set()
            if heartbeat_thread is not None:
                heartbeat_thread.join(timeout=THREAD_JOIN_TIMEOUT)
            pool.shutdown(wait=not interrupted, cancel_futures=True)
        total_time = time.time() - start
        return (
            total_time, results_list,
            peak_threads_ref, peak_client_rss_ref,
            peak_server_rss_ref, peak_sys_mem_pct_ref,
            peak_sys_cpu_ref,
            server_dead_event.is_set(), interrupted,
        )

    @staticmethod
    # pylint: disable=too-many-branches
    def _collect_with_timeout(
            futures, results_list, *,
            start, stage_timeout, cancel_event=None,
    ) -> Tuple[int, bool]:
        """Collect future results, cancelling stragglers on timeout/Ctrl-C.

        Polls in short slices so a set ``cancel_event`` (Ctrl-C) is
        noticed promptly: the event tells in-flight subprocesses to
        die, then their futures resolve as KILLED.  Returns
        (num_killed, interrupted).
        """
        pending = set(futures)
        killed = 0
        interrupted = False
        while pending:
            if cancel_event is not None and cancel_event.is_set():
                interrupted = True
                break
            elapsed = time.time() - start
            if stage_timeout is not None:
                remaining = stage_timeout - elapsed
                if remaining <= 0:
                    break
                wait_slice = min(1.0, remaining)
            else:
                wait_slice = 1.0
            try:
                for fut in as_completed(pending, timeout=wait_slice):
                    results_list.append(fut.result())
                    pending.discard(fut)
            except FutureTimeoutError:
                pass

        reason = (
            "Killed by Ctrl-C interrupt" if interrupted
            else "Killed by --stage-timeout"
        )
        for fut in pending:
            fut.cancel()
        if interrupted:
            # Give in-flight requests a short grace to wind down:
            # subprocess requests are killed via cancel_event and
            # resolve within a poll interval.  Anything still stuck
            # after the grace (e.g. an un-killable in-thread HTTP
            # request) is recorded as KILLED without blocking on it.
            grace_deadline = time.time() + INTERRUPT_GRACE_SECONDS
            for fut in list(pending):
                remaining = max(0.0, grace_deadline - time.time())
                try:
                    results_list.append(fut.result(timeout=remaining))
                    pending.discard(fut)
                except FutureTimeoutError:
                    pass
                except CancelledError:
                    pending.discard(fut)

        for fut in pending:
            killed += 1
            if fut.cancelled() or not fut.done():
                results_list.append({
                    "request_id": "unknown",
                    "status": STATUS_KILLED,
                    "stdout": "",
                    "stderr": reason,
                    "returncode": -1,
                    "elapsed": time.time() - start,
                    "ttft": 0.0,
                    "prompt": "",
                })
            else:
                results_list.append(fut.result())
        return killed, interrupted

    def _diagnose_failure(self, returncode, parsed_fields,
                          stdout) -> str:
        """Return a human-readable reason why a request was marked FAILED."""
        reasons = []
        if returncode != 0:
            reasons.append(f"non-zero exit code ({returncode})")
        for field in self._profile.success_fields:
            if field == "reservation_id" and self._args.skip_reservation_check:
                continue
            if not parsed_fields.get(field):
                reasons.append(f"missing {field}")
        token_hint = self._detect_empty_llm_response(stdout)
        if token_hint:
            reasons.append(token_hint)
        return "; ".join(reasons) if reasons else "unknown"

    @staticmethod
    def _detect_empty_llm_response(stdout) -> Optional[str]:
        """Check token accounting for signs of an empty LLM response."""
        tokens = CliBuilder.parse_token_accounting(stdout)
        if not tokens:
            return "no token data"
        empty = tokens.get("empty_responses", 0)
        completion = tokens.get("completion_tokens", 0)
        if empty > 0:
            return (
                f"empty LLM response "
                f"({completion} completion tokens, "
                f"{empty} empty response(s))"
            )
        return "incomplete response"

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
        if is_failure:
            with self._failure_log_lock:
                self._failures_logged += 1
                rank = self._failures_logged
            if rank > FAILURE_LOG_LIMIT:
                return
            if rank == FAILURE_LOG_LIMIT:
                sys.stdout.write("\n")
                sys.stdout.flush()
                logger.info(
                    "Request %s: %s (%s)",
                    request_id, status,
                    Formatters.fmt_duration(elapsed, precision=2),
                )
                logger.info(
                    "  ... further per-request failures suppressed"
                    " (see totals below and raw_results.json)",
                )
                return
        sys.stdout.write("\n")
        sys.stdout.flush()
        logger.info(
            "Request %s: %s (%s)",
            request_id, status,
            Formatters.fmt_duration(elapsed, precision=2),
        )
        for field, value in parsed_fields.items():
            if field == "reservation_id" and self._args.skip_reservation_check:
                logger.info("  %s: skipped", field)
            else:
                logger.info("  %s: %s", field, value or "")
        if failure_reason:
            logger.info("  reason: %s", failure_reason)
        if is_failure:
            last_err = CliBuilder.last_stderr_line(stderr)
            if last_err and last_err.strip():
                logger.info("  stderr: %s", last_err)

    @staticmethod
    def _write_result_to_file(output_dir, request_id, status,
                              elapsed, *, parsed_fields) -> None:
        """Append a successful request result to progress.log."""
        path = os.path.join(output_dir, "progress.log")
        fields_str = "  ".join(
            f"{k}: {v or ''}" for k, v in parsed_fields.items()
        )
        line = (
            f"Request {request_id}: {status}"
            f" ({Formatters.fmt_duration(elapsed, precision=2)})"
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
        agent = result.get("reporting_agent", "")
        elapsed = result.get("elapsed", 0)
        status = result.get("status", "?")
        agent_suffix = f", agent={agent}" if agent else ""
        fh.write(
            f"{rid}: {total:,} tokens, "
            f"{llm_calls} LLM call(s), "
            f"model={model}{agent_suffix}"
            f"  [{elapsed:.1f}s {status}]\n"
        )
        TrafficRunner._write_validation_detail(
            fh, rid, by_validation,
        )
        server_rid = result.get("server_request_id", rid)
        agents = (
            by_request.get(server_rid)
            or by_request.get(rid)
            or []
        )
        if not agents and agent:
            fh.write(
                f"  {agent}: {llm_calls} call(s)"
                f"  {total:,} tokens"
                f" ({result.get('prompt_tokens', 0):,} prompt"
                f" / {result.get('completion_tokens', 0):,}"
                f" completion)\n"
            )
        elif not agents and not agent:
            fh.write(
                "  (agent data not found in server log)\n"
            )
        for ag_entry in agents:
            net = ag_entry.get("network", "?")
            a_calls = ag_entry.get("llm_calls", 0)
            a_total = ag_entry.get("total_tokens", 0)
            a_prompt = ag_entry.get("prompt_tokens", 0)
            a_comp = ag_entry.get("completion_tokens", 0)
            fh.write(
                f"  {net}: {a_calls} call(s)"
                f"  {a_total:,} tokens"
                f" ({a_prompt:,} prompt"
                f" / {a_comp:,} completion)\n"
            )
        if agents or agent or rid in by_validation:
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
