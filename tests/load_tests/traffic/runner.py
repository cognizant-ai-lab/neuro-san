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
import sys
import threading
import time
from concurrent.futures import as_completed
from concurrent.futures import CancelledError
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

from leaf_common.parsers.dictionary_extractor import DictionaryExtractor

from neuro_san.message.processors.basic_message_processor import BasicMessageProcessor
from neuro_san.test.driver.assert_capture import AssertCapture
from neuro_san.test.driver.data_driven_tests_driver import DataDrivenTestsDriver

from tests.load_tests.config import FAILURE_LOG_LIMIT
from tests.load_tests.config import FAILURE_REASON_LINE_LIMIT
from tests.load_tests.config import Formatters
from tests.load_tests.config import RequestResult
from tests.load_tests.config import SharedRef
from tests.load_tests.config import STATUS_CREATED
from tests.load_tests.config import STATUS_FAILED
from tests.load_tests.config import STATUS_KILLED
from tests.load_tests.config import STATUS_TIMEOUT
from tests.load_tests.config import THREAD_JOIN_TIMEOUT
from tests.load_tests.cost_estimator import CostEstimator
from tests.load_tests.monitoring.heartbeat import Heartbeat
from tests.load_tests.traffic.http_client import HttpClient
from tests.load_tests.traffic.load_test_assert_forwarder import LoadTestAssertForwarder
from tests.load_tests.traffic.output_parser import OutputParser

logger = logging.getLogger(__name__)

# Grace period after Ctrl-C for in-flight requests to wind down before
# they are recorded as KILLED.
INTERRUPT_GRACE_SECONDS = 2.0


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
                         output_dir, failed_ref) -> RequestResult:
        """Run one request and increment failed_ref on failure."""
        result = self.run_one_http(
            request_id, global_request_id, output_dir,
        )
        if result.get("status") != STATUS_CREATED:
            failed_ref.value = (failed_ref.value or 0) + 1
        return result

    # pylint: disable=too-many-locals,too-many-branches
    def run_one_http(self, request_id, global_request_id,
                     output_dir=None) -> RequestResult:
        """Execute a single request via in-thread HTTP."""
        prompt = self._profile.get_prompt(
            global_request_id,
            same_prompt=self._args.same_prompt,
            allow_caching=self._args.allow_caching,
        )
        start = time.time()
        status, processor, response_text, ttft, token_data = (
            HttpClient.execute_request(
                self._args.host, self._args.port,
                self._args.agent, prompt,
                timeout=self._args.request_timeout,
                idle_timeout=self._args.idle_timeout,
                use_https=getattr(self._args, "https", False),
                chat_filter_type=getattr(
                    self._args, "chat_filter", "maximal",
                ).upper(),
            )
        )
        elapsed = time.time() - start

        parsed_fields = (
            HttpClient.flatten_string_fields(processor.get_sly_data())
            if processor is not None else {}
        )
        failure_reason = None
        if status == STATUS_CREATED:
            failure_reason = self.check_response(
                processor,
                self._profile.get_response(
                    global_request_id,
                    same_prompt=self._args.same_prompt,
                ),
            )
            if failure_reason:
                status = STATUS_FAILED
        elif status == STATUS_FAILED and not response_text:
            failure_reason = "empty response from agent"

        # A FAILED status with no failure_reason means HttpClient caught an
        # exception and returned its traceback as response_text. Route that
        # to stderr instead of saving it as the agent's answer.
        stderr = ""
        stdout = self._http_saved_stdout(response_text, token_data)
        if status == STATUS_FAILED and failure_reason is None:
            stderr = response_text
            stdout = ""
            failure_reason = OutputParser.last_stderr_line(stderr)

        self._save_request_output(
            output_dir, request_id, stdout, stderr,
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
                failure_reason
                if status != STATUS_CREATED else None
            ),
        }
        result.update(parsed_fields)
        if token_data:
            self._attach_http_token_data(result, token_data)
        return result

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

    def check_response(self, processor: BasicMessageProcessor,
                       response_checks: Dict[str, Any]) -> Optional[str]:
        """
        Apply the data-driven response checks to one completed request.

        Reuses the test framework: DataDrivenTestsDriver.test_response_keys
        walks the hocon ``response`` block (text / structure / sly_data)
        and dispatches each leaf to its AgentEvaluator (keywords, value,
        not_value, gist, ...). The profile's failure_patterns are the
        same thing as ``text: { not_keywords: [...] }`` and are checked
        through the same path. An AssertCapture collects the failed
        assertions instead of raising, so one request never stops the
        run.

        :param processor: The BasicMessageProcessor that saw the whole response stream
        :param response_checks: The hocon ``response`` block for this request's prompt
        :return: A one-line reason when any check failed, else None
        """
        asserts = AssertCapture(LoadTestAssertForwarder())
        driver = DataDrivenTestsDriver(asserts)
        blocks = [response_checks]
        if self._profile.failure_patterns:
            blocks.append(
                {"text": {"not_keywords": self._profile.failure_patterns}},
            )
        reasons: List[str] = []
        for block in blocks:
            extractor = DictionaryExtractor(block)
            # One test_response_keys call per top-level test key
            # (text, sly_data.<field>, ...) so each failure can be
            # labelled with the key it belongs to; the evaluators'
            # own messages only show the compared values.
            for key in self._top_level_keys(block):
                seen = len(asserts.get_asserts())
                driver.test_response_keys(
                    processor, extractor, [key], asserts, [],
                )
                for failure in asserts.get_asserts()[seen:]:
                    reasons.append(f"{key}: {self._first_line(str(failure))}")
        if not reasons:
            return None
        return "; ".join(reasons)

    @staticmethod
    def _top_level_keys(block: Dict[str, Any]) -> List[str]:
        """
        Return the test keys of a response block.

        :param block: A hocon ``response`` block
        :return: text and structure when present, plus sly_data.<field>
                 for each field under sly_data
        """
        keys: List[str] = []
        for test_key in DataDrivenTestsDriver.TEST_KEYS:
            checks = block.get(test_key)
            if checks is None:
                continue
            if test_key == "sly_data" and isinstance(checks, dict):
                for field in checks:
                    keys.append(f"{test_key}.{field}")
            else:
                keys.append(test_key)
        return keys

    @staticmethod
    def _first_line(message: str) -> str:
        """
        Return the first non-empty line of an assertion message, shortened.

        :param message: The AssertionError text, possibly multi-line
        :return: Its first non-empty line, cut to FAILURE_REASON_LINE_LIMIT
        """
        line: str = message
        for part in message.splitlines():
            if part.strip():
                line = part
                break
        line = line.strip()
        if len(line) <= FAILURE_REASON_LINE_LIMIT:
            return line
        return line[:FAILURE_REASON_LINE_LIMIT - 3] + "..."

    def _http_saved_stdout(self, response_text, token_data) -> str:
        """Final answer plus Token Accounting JSON, joined so the saved
        per-request file carries both.
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

        Accepts the token_accounting dict directly instead of
        parsing from stdout.
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
        SharedRef, SharedRef, SharedRef, SharedRef, bool, bool,
    ]:
        """Fire num_requests concurrent requests using a thread pool.

        Returns (elapsed, results, peak_threads_ref,
        peak_client_rss_ref, peak_server_rss_ref,
        peak_sys_mem_pct_ref, peak_sys_cpu_ref,
        peak_sys_threads_ref, server_died, interrupted).

        When ``cancel_event`` becomes set (Ctrl-C), the stage returns early
        with whatever completed so far, marking the remainder KILLED.
        """
        results_list: List[RequestResult] = []
        peak_threads_ref = SharedRef()
        peak_client_rss_ref = SharedRef()
        peak_server_rss_ref = SharedRef()
        peak_sys_mem_pct_ref = SharedRef()
        peak_sys_cpu_ref = SharedRef()
        peak_sys_threads_ref = SharedRef()
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
                    "peak_sys_threads_ref": peak_sys_threads_ref,
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
                    output_dir, failed_ref,
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
            peak_sys_cpu_ref, peak_sys_threads_ref,
            server_dead_event.is_set(), interrupted,
        )

    @staticmethod
    # pylint: disable=too-many-branches
    def _collect_with_timeout(
            futures, results_list, *,
            start, stage_timeout, cancel_event=None,
    ) -> Tuple[int, bool]:
        """Collect future results, cancelling stragglers on timeout/Ctrl-C.

        Polls in short slices so a set ``cancel_event`` (Ctrl-C) is noticed
        promptly. Returns (num_killed, interrupted).
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
            # Give in-flight requests a short grace to wind down; anything
            # still stuck after the grace is recorded as KILLED without
            # blocking on it.
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
            logger.info("  %s: %s", field, value or "")
        if failure_reason:
            logger.info("  reason: %s", failure_reason)
        if is_failure:
            last_err = OutputParser.last_stderr_line(stderr)
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
