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
from argparse import Namespace
from concurrent.futures import as_completed
from concurrent.futures import CancelledError
from concurrent.futures import Future
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Set
from typing import Tuple

import psutil

from leaf_common.parsers.dictionary_extractor import DictionaryExtractor

from neuro_san.message.processors.basic_message_processor import BasicMessageProcessor
from neuro_san.test.driver.assert_capture import AssertCapture
from neuro_san.test.driver.data_driven_tests_driver import DataDrivenTestsDriver

from tests.load_tests.config import FAILURE_LOG_LIMIT
from tests.load_tests.config import FAILURE_REASON_LINE_LIMIT
from tests.load_tests.config import STATUS_CREATED
from tests.load_tests.config import STATUS_FAILED
from tests.load_tests.config import STATUS_KILLED
from tests.load_tests.config import THREAD_JOIN_TIMEOUT
from tests.load_tests.cost_estimator import CostEstimator
from tests.load_tests.monitoring.heartbeat import Heartbeat
from tests.load_tests.monitoring.server_log_monitor import ServerLogMonitor
from tests.load_tests.prompts.agent_profile import AgentProfile
from tests.load_tests.reporting.formatters import Formatters
from tests.load_tests.reporting.sly_data_flattener import SlyDataFlattener
from tests.load_tests.shared_ref import SharedRef
from tests.load_tests.traffic.agent_request_executor import AgentRequestExecutor
from tests.load_tests.traffic.agent_request_result import AgentRequestResult
from tests.load_tests.traffic.load_test_assert_forwarder import LoadTestAssertForwarder
from tests.load_tests.traffic.output_parser import OutputParser
from tests.load_tests.traffic.request_status_policy import RequestStatusPolicy
from tests.load_tests.traffic.stage_plan import StagePlan

logger = logging.getLogger(__name__)

# Grace period after Ctrl-C for in-flight requests to wind down before
# they are recorded as KILLED.
INTERRUPT_GRACE_SECONDS = 2.0


class TrafficRunner:
    """Fires concurrent requests via a thread pool and collects results.

    Holds the parsed CLI args and the agent profile so that callers
    do not need to thread them through every method.
    """

    def __init__(self, args: Namespace, profile: AgentProfile, cancel_event: threading.Event) -> None:
        """
        :param args: Parsed load-test command line
        :param profile: Prompts and response checks for the agent under test
        :param cancel_event: Set by the Ctrl-C handler to stop a stage early
        """
        self._args: Namespace = args
        self._profile: AgentProfile = profile
        self._cancel_event: threading.Event = cancel_event
        self._failure_log_lock: threading.Lock = threading.Lock()
        self._failures_logged: int = 0

    def _run_one_tracked(self, request_id: int, global_request_id: int,
                         output_dir: Optional[str], failed_ref: SharedRef) -> Dict[str, Any]:
        """
        Run one request and increment failed_ref on failure.

        :param request_id: Request number within the current stage
        :param global_request_id: Request number across the whole run
        :param output_dir: Directory for per-request output files, or None
        :param failed_ref: Shared counter of failed requests
        :return: The request result
        """
        result: Dict[str, Any] = self.run_one_http(request_id, global_request_id, output_dir)
        if result.get("status") != STATUS_CREATED:
            failed_ref.value = (failed_ref.value or 0) + 1
        return result

    def run_one_http(self, request_id: int, global_request_id: int, output_dir: Optional[str] = None) -> Dict[str, Any]:
        """
        Execute a single request via in-thread HTTP and check its response.

        :param request_id: Request number within the current stage
        :param global_request_id: Request number across the whole run,
                                  used to pick the prompt and its response checks
        :param output_dir: Directory for per-request output files, or None
        :return: The request result
        """
        prompt: str = self._profile.get_prompt(global_request_id, same_prompt=self._args.same_prompt,
                                               allow_caching=self._args.allow_caching)
        start_unix_seconds: float = time.time()
        start_seconds: float = time.perf_counter()
        request_result: AgentRequestResult = AgentRequestExecutor.execute_request(
            self._args.host, self._args.port,
            self._args.agent, prompt,
            timeout=self._args.request_timeout,
            idle_timeout=self._args.idle_timeout,
            use_https=self._args.https,
            chat_filter_type=self._args.chat_filter.upper(),
        )
        elapsed_seconds: float = time.perf_counter() - start_seconds
        status: str = request_result.get_status()
        failure_reason: Optional[str] = self._failure_reason(request_result, global_request_id)
        if status == STATUS_CREATED and failure_reason:
            status = STATUS_FAILED

        result: Dict[str, Any] = {
            "request_id": f"request-{request_id}",
            "status": status,
            "elapsed": elapsed_seconds,
            "time_to_first_response": request_result.get_time_to_first_response(),
            "start_time": start_unix_seconds,
            "end_time": start_unix_seconds + elapsed_seconds,
            "prompt": prompt,
            "failure_reason": failure_reason,
            "error": failure_reason if status != STATUS_CREATED else None,
        }
        self._record_request(request_id, output_dir, request_result, result)
        return result

    def _failure_reason(self, request_result: AgentRequestResult, global_request_id: int) -> Optional[str]:
        """
        Work out why a request failed.

        :param request_result: What AgentRequestExecutor returned for the request
        :param global_request_id: Request number across the whole run,
                                  used to pick the response checks
        :return: The failure reason, or None when the request did not fail
        """
        status: str = request_result.get_status()
        response_text: str = request_result.get_response_text()
        if status == STATUS_CREATED:
            return self.check_response(
                request_result.get_processor(),
                self._profile.get_response(
                    global_request_id,
                    same_prompt=self._args.same_prompt,
                ),
            )
        if status != STATUS_FAILED:
            return None
        if not RequestStatusPolicy.is_traceback(status, response_text):
            return "empty response from agent"
        return OutputParser.last_stderr_line(response_text)

    def _record_request(self, request_id: int, output_dir: Optional[str],
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
            parsed_fields = SlyDataFlattener.flatten_string_fields(processor.get_sly_data())

        # A traceback goes to stderr instead of being saved as the agent's answer.
        stderr: str = ""
        stdout: str = self._http_saved_stdout(response_text, token_data)
        if RequestStatusPolicy.is_traceback(request_result.get_status(), response_text):
            stderr = response_text
            stdout = ""

        self._save_request_output(output_dir, request_id, stdout, stderr)

        status: str = result.get("status")
        if output_dir and not RequestStatusPolicy.is_failure(status):
            self._write_result_to_file(output_dir, request_id, status, result.get("elapsed"),
                                       parsed_fields=parsed_fields)
        else:
            self._log_request_result(request_id, result, parsed_fields=parsed_fields, stderr=stderr)

        result.update(parsed_fields)
        if token_data:
            self._attach_http_token_data(result, token_data)

    @staticmethod
    def _extract_model(models_dict: Dict[str, Any]) -> str:
        """
        Extract the specific model name from the nested models dict.

        Token Accounting returns: {"openai": {"gpt-4o-mini": {...}}}.
        This traverses provider -> model to return "gpt-4o-mini".

        :param models_dict: Token Accounting "models" dict, provider -> model -> usage
        :return: First model name found, or "unknown"
        """
        for provider_models in models_dict.values():
            if isinstance(provider_models, dict):
                for model_name in provider_models:
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
        for provider_models in models_dict.values():
            if isinstance(provider_models, dict):
                all_models.extend(provider_models.keys())
        return all_models

    def check_response(self, processor: BasicMessageProcessor, response_checks: Dict[str, Any]) -> Optional[str]:
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
        asserts: AssertCapture = AssertCapture(LoadTestAssertForwarder())
        driver: DataDrivenTestsDriver = DataDrivenTestsDriver(asserts)
        blocks: List[Dict[str, Any]] = [response_checks]
        if self._profile.get_failure_patterns():
            blocks.append({"text": {"not_keywords": self._profile.get_failure_patterns()}})
        reasons: List[str] = []
        for block in blocks:
            extractor: DictionaryExtractor = DictionaryExtractor(block)
            # One test_response_keys call per top-level test key
            # (text, sly_data.<field>, ...) so each failure can be
            # labelled with the key it belongs to; the evaluators'
            # own messages only show the compared values.
            for key in self._top_level_keys(block):
                seen: int = len(asserts.get_asserts())
                driver.test_response_keys(processor, extractor, [key], asserts, [])
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
            checks: Any = block.get(test_key)
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

    def _http_saved_stdout(self, response_text: str, token_data: Optional[Dict[str, Any]]) -> str:
        """
        Join the final answer and the Token Accounting JSON for the saved per-request file.

        :param response_text: Final answer text of the request
        :param token_data: Token Accounting dict from the response, or None
        :return: Text to save as the request's stdout
        """
        saved: str = response_text or ""
        if self._args.include_tokens and token_data:
            saved += "\n\nToken Accounting:\n" + json.dumps(token_data, indent=2) + "\n"
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
        model: str = TrafficRunner._extract_model(models_dict)
        all_models: List[str] = TrafficRunner._extract_all_models(models_dict)
        prompt_tokens: int = token_data.get("prompt_tokens", 0)
        completion_tokens: int = token_data.get("completion_tokens", 0)
        result.update({
            "total_tokens": token_data.get("total_tokens", 0),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "llm_calls": token_data.get(
                "successful_requests", 0,
            ),
            "model": model,
            "all_models": all_models,
            "cost_usd": CostEstimator.estimate(
                prompt_tokens, completion_tokens, model,
            ),
        })

    def run_stage(self, plan: StagePlan,
                  server_proc: Optional[psutil.Process] = None,
                  client_proc: Optional[psutil.Process] = None,
                  log_monitor: Optional[ServerLogMonitor] = None,
                  ) -> Tuple[
        float, List[Dict[str, Any]], SharedRef, SharedRef,
        SharedRef, SharedRef, SharedRef, SharedRef, bool, bool,
    ]:
        """
        Fire the stage's requests concurrently using a thread pool.

        When the Ctrl-C cancel_event becomes set, the stage returns early
        with whatever completed so far, marking the remainder KILLED.

        :param plan: Request count, pool size, request numbering and output directory of the stage
        :param server_proc: Server process for the heartbeat's resource readings, or None
        :param client_proc: Client process for the heartbeat's resource readings, or None
        :param log_monitor: Server log reader for server-side request timing, or None
        :return: (total_time_seconds, results, peak_threads_ref, peak_client_rss_ref,
                 peak_server_rss_ref, peak_sys_mem_pct_ref, peak_sys_cpu_ref,
                 peak_sys_threads_ref, server_died, interrupted)
        """
        results_list: List[Dict[str, Any]] = []
        heartbeat_kwargs: Dict[str, Any] = TrafficRunner._new_heartbeat_kwargs()
        start_seconds: float = time.perf_counter()
        interrupted: bool = False
        heartbeat_thread: Optional[threading.Thread] = None
        # Not using ``with`` so that on Ctrl-C we can shut the pool
        # down without blocking on stalled worker threads (e.g.
        # in-thread HTTP requests that cannot be force-killed).
        pool: ThreadPoolExecutor = ThreadPoolExecutor(max_workers=plan.get_max_workers())
        try:
            futures_ref: List[Future] = []
            heartbeat: Heartbeat = self._create_heartbeat(server_proc, client_proc, plan.get_output_dir(), log_monitor)
            heartbeat_thread = threading.Thread(target=heartbeat.progress_heartbeat,
                                                args=(futures_ref, plan.get_num_requests(), start_seconds),
                                                kwargs=heartbeat_kwargs, daemon=True)
            heartbeat_thread.start()
            heartbeat_kwargs.get("ready_event").wait()
            self._submit_requests(pool, plan, futures_ref, heartbeat_kwargs.get("failed_ref"))
            heartbeat_kwargs.get("fires_done_event").set()
            killed_count: int
            killed_count, interrupted = self._collect_with_timeout(
                futures_ref, results_list,
                start_seconds=start_seconds, stage_timeout_seconds=self._args.stage_timeout,
                cancel_event=self._cancel_event,
            )
            if killed_count and not interrupted:
                logger.warning("  Stage timeout (%ss) reached — %s request(s) killed.", self._args.stage_timeout,
                               killed_count)
            elif interrupted:
                logger.warning(
                    "  Interrupted (Ctrl-C) — %s request(s) still "
                    "in flight were dropped; reporting completed ones.",
                    killed_count,
                )
        finally:
            heartbeat_kwargs.get("stop_event").set()
            if heartbeat_thread is not None:
                heartbeat_thread.join(timeout=THREAD_JOIN_TIMEOUT)
            pool.shutdown(wait=not interrupted, cancel_futures=True)
        total_time_seconds: float = time.perf_counter() - start_seconds
        return (
            total_time_seconds, results_list,
            heartbeat_kwargs.get("peak_threads_ref"), heartbeat_kwargs.get("peak_client_rss_ref"),
            heartbeat_kwargs.get("peak_server_rss_ref"), heartbeat_kwargs.get("peak_sys_mem_pct_ref"),
            heartbeat_kwargs.get("peak_sys_cpu_ref"), heartbeat_kwargs.get("peak_sys_threads_ref"),
            heartbeat_kwargs.get("server_dead_event").is_set(), interrupted,
        )

    @staticmethod
    def _new_heartbeat_kwargs() -> Dict[str, Any]:
        """
        Create the events and shared values that Heartbeat.progress_heartbeat() uses during a stage.

        :return: Keyword arguments for Heartbeat.progress_heartbeat(), keyed by its parameter names
        """
        heartbeat_kwargs: Dict[str, Any] = {}
        for event_name in ("stop_event", "ready_event", "fires_done_event", "server_dead_event"):
            heartbeat_kwargs[event_name] = threading.Event()
        for ref_name in ("peak_threads_ref", "peak_client_rss_ref", "peak_server_rss_ref",
                         "peak_sys_mem_pct_ref", "peak_sys_cpu_ref", "peak_sys_threads_ref", "failed_ref"):
            heartbeat_kwargs[ref_name] = SharedRef()
        heartbeat_kwargs.get("failed_ref").value = 0
        return heartbeat_kwargs

    def _create_heartbeat(self, server_proc: Optional[psutil.Process], client_proc: Optional[psutil.Process],
                          output_dir: Optional[str], log_monitor: Optional[ServerLogMonitor]) -> Heartbeat:
        """
        Create the stage's Heartbeat, reading the server log from its current end.

        :param server_proc: Server process for resource readings, or None
        :param client_proc: Client process for resource readings, or None
        :param output_dir: Directory for progress.log, or None
        :param log_monitor: Server log reader for server-side request timing, or None
        :return: The Heartbeat
        """
        log_start_pos: Optional[int] = None
        if log_monitor is not None:
            log_start_pos = log_monitor.read_position()
        return Heartbeat(server_proc, client_proc, output_dir, log_monitor=log_monitor, log_start_pos=log_start_pos,
                         primary_start_pattern=self._profile.get_primary_start_pattern())

    def _submit_requests(self, pool: ThreadPoolExecutor, plan: StagePlan, futures: List[Future],
                         failed_ref: SharedRef) -> None:
        """
        Submit every request of the stage to the pool.

        :param pool: Thread pool of the stage
        :param plan: Request count, request numbering and output directory of the stage
        :param futures: Receives one future per request; the heartbeat reads it while requests run
        :param failed_ref: Shared counter of failed requests
        """
        for index in range(plan.get_num_requests()):
            future: Future = pool.submit(self._run_one_tracked, index + 1, plan.get_global_offset() + index,
                                         plan.get_output_dir(), failed_ref)
            futures.append(future)

    @staticmethod
    def _collect_with_timeout(futures: List[Future], results_list: List[Dict[str, Any]], start_seconds: float,
                              stage_timeout_seconds: Optional[float],
                              cancel_event: threading.Event) -> Tuple[int, bool]:
        """
        Collect future results, cancelling stragglers on timeout/Ctrl-C.

        Polls in short slices so a set cancel_event (Ctrl-C) is noticed promptly.

        :param futures: Futures of the requests fired in this stage
        :param results_list: Receives one RequestResult per future, KILLED for stragglers
        :param start_seconds: time.perf_counter() when the stage began
        :param stage_timeout_seconds: Seconds after which unfinished requests are killed, or None
        :param cancel_event: Set by the Ctrl-C handler to stop collecting early
        :return: (num_killed, interrupted)
        """
        pending_futures: Set[Future] = set(futures)
        interrupted: bool = False
        elapsed_seconds: float
        remaining_seconds: float
        wait_slice_seconds: float
        while pending_futures:
            if cancel_event.is_set():
                interrupted = True
                break
            elapsed_seconds = time.perf_counter() - start_seconds
            if stage_timeout_seconds is not None:
                remaining_seconds = stage_timeout_seconds - elapsed_seconds
                if remaining_seconds <= 0:
                    break
                wait_slice_seconds = min(1.0, remaining_seconds)
            else:
                wait_slice_seconds = 1.0
            try:
                for future in as_completed(pending_futures, timeout=wait_slice_seconds):
                    results_list.append(future.result())
                    pending_futures.discard(future)
            except FutureTimeoutError:
                pass

        reason: str = "Killed by --stage-timeout"
        if interrupted:
            reason = "Killed by Ctrl-C interrupt"
        for future in pending_futures:
            future.cancel()
        if interrupted:
            TrafficRunner._collect_during_grace(pending_futures, results_list)
        killed: int = TrafficRunner._collect_killed(
            pending_futures, results_list, start_seconds=start_seconds, reason=reason,
        )
        return killed, interrupted

    @staticmethod
    def _collect_during_grace(pending_futures: Set[Future], results_list: List[Dict[str, Any]]) -> None:
        """
        Give in-flight requests a short grace to wind down after Ctrl-C.

        Anything still stuck after the grace stays in pending_futures, without blocking on it.

        :param pending_futures: Futures not collected yet, updated in place
        :param results_list: Receives the results that finish within the grace
        """
        grace_deadline_seconds: float = time.perf_counter() + INTERRUPT_GRACE_SECONDS
        remaining_seconds: float
        for future in list(pending_futures):
            remaining_seconds = max(0.0, grace_deadline_seconds - time.perf_counter())
            try:
                results_list.append(future.result(timeout=remaining_seconds))
                pending_futures.discard(future)
            except FutureTimeoutError:
                pass
            except CancelledError:
                pending_futures.discard(future)

    @staticmethod
    def _collect_killed(pending_futures: Set[Future], results_list: List[Dict[str, Any]], start_seconds: float,
                        reason: str) -> int:
        """
        Record the futures still pending, KILLED unless they finished meanwhile.

        :param pending_futures: Futures not collected yet
        :param results_list: Receives one result per pending future
        :param start_seconds: time.perf_counter() when the stage began
        :param reason: Why the stragglers were killed, saved as their stderr
        :return: Number of pending futures
        """
        killed: int = 0
        for future in pending_futures:
            killed += 1
            if future.cancelled() or not future.done():
                results_list.append({
                    "request_id": "unknown",
                    "status": STATUS_KILLED,
                    "stdout": "",
                    "stderr": reason,
                    "returncode": -1,
                    "elapsed": time.perf_counter() - start_seconds,
                    "time_to_first_response": 0.0,
                    "prompt": "",
                })
            else:
                results_list.append(future.result())
        return killed

    def _log_request_result(self, request_id: int, result: Dict[str, Any],
                            parsed_fields: Dict[str, str], stderr: str) -> None:
        """
        Log the result of a single request to the console.

        FAILED/TIMEOUT/KILLED print up to FAILURE_LOG_LIMIT.

        :param request_id: Request number within the current stage
        :param result: The request result, with status, elapsed and failure_reason
        :param parsed_fields: Flattened sly_data string fields of the response
        :param stderr: Error text captured for the request
        """
        status: str = result.get("status")
        elapsed_seconds: float = result.get("elapsed")
        failure_reason: Optional[str] = result.get("failure_reason")
        is_failure: bool = RequestStatusPolicy.is_failure(status)
        if is_failure:
            rank: int
            with self._failure_log_lock:
                self._failures_logged += 1
                rank = self._failures_logged
            if rank > FAILURE_LOG_LIMIT:
                return
            if rank == FAILURE_LOG_LIMIT:
                sys.stdout.write("\n")
                sys.stdout.flush()
                logger.info("Request %s: %s (%s)", request_id, status,
                            Formatters.fmt_duration(elapsed_seconds, precision=2))
                logger.info("  ... further per-request failures suppressed (see totals below and raw_results.json)")
                return
        sys.stdout.write("\n")
        sys.stdout.flush()
        logger.info("Request %s: %s (%s)", request_id, status, Formatters.fmt_duration(elapsed_seconds, precision=2))
        for field, value in parsed_fields.items():
            logger.info("  %s: %s", field, value or "")
        if failure_reason:
            logger.info("  reason: %s", failure_reason)
        if is_failure:
            last_error_line: Optional[str] = OutputParser.last_stderr_line(stderr)
            if last_error_line and last_error_line.strip():
                logger.info("  stderr: %s", last_error_line)

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
        path: str = os.path.join(output_dir, "progress.log")
        field_parts: List[str] = []
        for key, value in parsed_fields.items():
            field_parts.append(f"{key}: {value or ''}")
        fields_str: str = "  ".join(field_parts)
        line: str = (
            f"Request {request_id}: {status}"
            f" ({Formatters.fmt_duration(elapsed_seconds, precision=2)})"
            f"  {fields_str}\n"
        )
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line)

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
        requests_dir: str = os.path.join(output_dir, "requests")
        os.makedirs(requests_dir, exist_ok=True)
        stdout_path: str = os.path.join(requests_dir, f"request_{request_id}_stdout.txt")
        with open(stdout_path, "w", encoding="utf-8") as fh:
            fh.write(stdout)
        if stderr and stderr.strip():
            stderr_path: str = os.path.join(requests_dir, f"request_{request_id}_stderr.txt")
            with open(stderr_path, "w", encoding="utf-8") as fh:
                fh.write(stderr)
