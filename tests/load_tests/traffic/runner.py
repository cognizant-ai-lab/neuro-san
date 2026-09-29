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
from typing import TextIO
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
from tests.load_tests.config import STATUS_TIMEOUT
from tests.load_tests.config import THREAD_JOIN_TIMEOUT
from tests.load_tests.cost_estimator import CostEstimator
from tests.load_tests.monitoring.heartbeat import Heartbeat
from tests.load_tests.monitoring.server_log_monitor import ServerLogMonitor
from tests.load_tests.prompts.agent_profile import AgentProfile
from tests.load_tests.records.network_token_entry import NetworkTokenEntry
from tests.load_tests.records.request_result import RequestResult
from tests.load_tests.records.validation_event import ValidationEvent
from tests.load_tests.reporting.formatters import Formatters
from tests.load_tests.reporting.sly_data_flattener import SlyDataFlattener
from tests.load_tests.shared_ref import SharedRef
from tests.load_tests.traffic.agent_request_executor import AgentRequestExecutor
from tests.load_tests.traffic.agent_request_result import AgentRequestResult
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

    def __init__(self, args: Namespace, profile: AgentProfile) -> None:
        """
        :param args: Parsed load-test command line
        :param profile: Prompts and response checks for the agent under test
        """
        self._args: Namespace = args
        self._profile: AgentProfile = profile
        self._failure_log_lock: threading.Lock = threading.Lock()
        self._failures_logged: int = 0

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def _run_one_tracked(self, request_id: int, global_request_id: int,
                         output_dir: Optional[str], failed_ref: SharedRef) -> RequestResult:
        """
        Run one request and increment failed_ref on failure.

        :param request_id: Request number within the current stage
        :param global_request_id: Request number across the whole run
        :param output_dir: Directory for per-request output files, or None
        :param failed_ref: Shared counter of failed requests
        :return: The request result
        """
        result: RequestResult = self.run_one_http(
            request_id, global_request_id, output_dir,
        )
        if result.get("status") != STATUS_CREATED:
            failed_ref.value = (failed_ref.value or 0) + 1
        return result

    # pylint: disable=too-many-locals,too-many-branches
    def run_one_http(self, request_id: int, global_request_id: int,
                     output_dir: Optional[str] = None) -> RequestResult:
        """
        Execute a single request via in-thread HTTP and check its response.

        :param request_id: Request number within the current stage
        :param global_request_id: Request number across the whole run,
                                  used to pick the prompt and its response checks
        :param output_dir: Directory for per-request output files, or None
        :return: The request result
        """
        prompt: str = self._profile.get_prompt(
            global_request_id,
            same_prompt=self._args.same_prompt,
            allow_caching=self._args.allow_caching,
        )
        start: float = time.time()
        request_result: AgentRequestResult = AgentRequestExecutor.execute_request(
            self._args.host, self._args.port,
            self._args.agent, prompt,
            timeout=self._args.request_timeout,
            idle_timeout=self._args.idle_timeout,
            use_https=getattr(self._args, "https", False),
            chat_filter_type=getattr(
                self._args, "chat_filter", "maximal",
            ).upper(),
        )
        elapsed: float = time.time() - start
        status: str = request_result.get_status()
        processor: Optional[BasicMessageProcessor] = request_result.get_processor()
        response_text: str = request_result.get_response_text()
        time_to_first_response: float = request_result.get_time_to_first_response()
        token_data: Dict[str, Any] = request_result.get_token_accounting()

        parsed_fields: Dict[str, str] = {}
        if processor is not None:
            parsed_fields = SlyDataFlattener.flatten_string_fields(processor.get_sly_data())
        failure_reason: Optional[str] = None
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

        # A FAILED status with no failure_reason means AgentRequestExecutor caught an
        # exception and returned its traceback as response_text. Route that
        # to stderr instead of saving it as the agent's answer.
        stderr: str = ""
        stdout: str = self._http_saved_stdout(response_text, token_data)
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

        result: RequestResult = {
            "request_id": f"request-{request_id}",
            "status": status,
            "elapsed": elapsed,
            "time_to_first_response": time_to_first_response,
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
        if self._profile.get_failure_patterns():
            blocks.append(
                {"text": {"not_keywords": self._profile.get_failure_patterns()}},
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

    def _http_saved_stdout(self, response_text: str,
                           token_data: Optional[Dict[str, Any]]) -> str:
        """
        Join the final answer and the Token Accounting JSON for the saved per-request file.

        :param response_text: Final answer text of the request
        :param token_data: Token Accounting dict from the response, or None
        :return: Text to save as the request's stdout
        """
        saved: str = response_text or ""
        if self._args.include_tokens and token_data:
            saved += (
                "\n\nToken Accounting:\n"
                + json.dumps(token_data, indent=2)
                + "\n"
            )
        return saved

    @staticmethod
    def _attach_http_token_data(result: RequestResult,
                                token_data: Optional[Dict[str, Any]]) -> None:
        """
        Attach token accounting from the HTTP response to the result.

        :param result: Request result to update in place
        :param token_data: Token Accounting dict from the response, or None
        """
        if not token_data:
            return
        models_dict: Dict[str, Any] = token_data.get("models", {})
        model: str = TrafficRunner._extract_model(models_dict)
        all_models: List[str] = TrafficRunner._extract_all_models(
            models_dict,
        )
        prompt_tok: int = token_data.get("prompt_tokens", 0)
        completion_tok: int = token_data.get("completion_tokens", 0)
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
    def run_stage(self, num_requests: int,
                  max_workers: int, global_offset: int, *,
                  server_proc: Optional[psutil.Process] = None,
                  client_proc: Optional[psutil.Process] = None,
                  output_dir: Optional[str] = None,
                  stage_timeout: Optional[float] = None,
                  cancel_event: Optional[threading.Event] = None,
                  log_monitor: Optional[ServerLogMonitor] = None,
                  primary_start_pattern: Optional[str] = None,
                  ) -> Tuple[
        float, List[RequestResult], SharedRef, SharedRef,
        SharedRef, SharedRef, SharedRef, SharedRef, bool, bool,
    ]:
        """
        Fire num_requests concurrent requests using a thread pool.

        When cancel_event becomes set (Ctrl-C), the stage returns early
        with whatever completed so far, marking the remainder KILLED.

        :param num_requests: Requests to fire in this stage
        :param max_workers: Thread pool size
        :param global_offset: Request number of the first request across the whole run
        :param server_proc: Server process for the heartbeat's resource readings, or None
        :param client_proc: Client process for the heartbeat's resource readings, or None
        :param output_dir: Directory for per-request output files, or None
        :param stage_timeout: Seconds after which unfinished requests are killed, or None
        :param cancel_event: Set by the Ctrl-C handler to stop the stage early
        :param log_monitor: Server log reader for server-side request timing, or None
        :param primary_start_pattern: Regex marking a primary request start in the server log
        :return: (elapsed, results, peak_threads_ref, peak_client_rss_ref,
                 peak_server_rss_ref, peak_sys_mem_pct_ref, peak_sys_cpu_ref,
                 peak_sys_threads_ref, server_died, interrupted)
        """
        results_list: List[RequestResult] = []
        peak_threads_ref: SharedRef = SharedRef()
        peak_client_rss_ref: SharedRef = SharedRef()
        peak_server_rss_ref: SharedRef = SharedRef()
        peak_sys_mem_pct_ref: SharedRef = SharedRef()
        peak_sys_cpu_ref: SharedRef = SharedRef()
        peak_sys_threads_ref: SharedRef = SharedRef()
        failed_ref: SharedRef = SharedRef()
        failed_ref.value = 0
        server_dead_event: threading.Event = threading.Event()
        start: float = time.time()
        interrupted: bool = False
        heartbeat_thread: Optional[threading.Thread] = None
        heartbeat_stop: threading.Event = threading.Event()
        # Not using ``with`` so that on Ctrl-C we can shut the pool
        # down without blocking on stalled worker threads (e.g.
        # in-thread HTTP requests that cannot be force-killed).
        pool: ThreadPoolExecutor = ThreadPoolExecutor(max_workers=max_workers)
        try:
            heartbeat_ready: threading.Event = threading.Event()
            fires_done_event: threading.Event = threading.Event()
            futures_ref: List[Future] = []
            log_start_pos: Optional[int] = None
            if log_monitor is not None:
                log_start_pos = log_monitor.read_position()
            hb: Heartbeat = Heartbeat(
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
            for i in range(num_requests):
                future: Future = pool.submit(
                    self._run_one_tracked,
                    i + 1, global_offset + i,
                    output_dir, failed_ref,
                )
                futures_ref.append(future)
            fires_done_event.set()
            killed_count: int
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
        total_time: float = time.time() - start
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
            futures: List[Future], results_list: List[RequestResult], *,
            start: float, stage_timeout: Optional[float],
            cancel_event: Optional[threading.Event] = None,
    ) -> Tuple[int, bool]:
        """
        Collect future results, cancelling stragglers on timeout/Ctrl-C.

        Polls in short slices so a set cancel_event (Ctrl-C) is noticed promptly.

        :param futures: Futures of the requests fired in this stage
        :param results_list: Receives one RequestResult per future, KILLED for stragglers
        :param start: time.time() when the stage began
        :param stage_timeout: Seconds after which unfinished requests are killed, or None
        :param cancel_event: Set by the Ctrl-C handler to stop collecting early
        :return: (num_killed, interrupted)
        """
        pending: Set[Future] = set(futures)
        killed: int = 0
        interrupted: bool = False
        elapsed: float
        remaining: float
        wait_slice: float
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

        reason: str = "Killed by --stage-timeout"
        if interrupted:
            reason = "Killed by Ctrl-C interrupt"
        for fut in pending:
            fut.cancel()
        if interrupted:
            # Give in-flight requests a short grace to wind down; anything
            # still stuck after the grace is recorded as KILLED without
            # blocking on it.
            grace_deadline: float = time.time() + INTERRUPT_GRACE_SECONDS
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
                    "time_to_first_response": 0.0,
                    "prompt": "",
                })
            else:
                results_list.append(fut.result())
        return killed, interrupted

    def _log_request_result(self, request_id: int, status: str, elapsed: float, *,
                            parsed_fields: Dict[str, str], failure_reason: Optional[str],
                            stderr: str, output_dir: Optional[str] = None) -> None:
        """
        Log the result of a single request.

        CREATED results go to progress.log when output_dir is set.
        FAILED/TIMEOUT/KILLED always print to console, up to FAILURE_LOG_LIMIT.

        :param request_id: Request number within the current stage
        :param status: One of the STATUS_* values
        :param elapsed: Request duration in seconds
        :param parsed_fields: Flattened sly_data string fields of the response
        :param failure_reason: Why the response check failed, or None
        :param stderr: Error text captured for the request
        :param output_dir: Directory holding progress.log, or None for console only
        """
        is_failure: bool = status in (
            STATUS_FAILED, STATUS_TIMEOUT, STATUS_KILLED,
        )
        if output_dir and not is_failure:
            self._write_result_to_file(
                output_dir, request_id, status, elapsed,
                parsed_fields=parsed_fields,
            )
            return
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
            last_err: Optional[str] = OutputParser.last_stderr_line(stderr)
            if last_err and last_err.strip():
                logger.info("  stderr: %s", last_err)

    @staticmethod
    def _write_result_to_file(output_dir: str, request_id: int, status: str,
                              elapsed: float, *, parsed_fields: Dict[str, str]) -> None:
        """
        Append a successful request result to progress.log.

        :param output_dir: Directory holding progress.log
        :param request_id: Request number within the current stage
        :param status: One of the STATUS_* values
        :param elapsed: Request duration in seconds
        :param parsed_fields: Flattened sly_data string fields of the response
        """
        path: str = os.path.join(output_dir, "progress.log")
        field_parts: List[str] = []
        for key, value in parsed_fields.items():
            field_parts.append(f"{key}: {value or ''}")
        fields_str: str = "  ".join(field_parts)
        line: str = (
            f"Request {request_id}: {status}"
            f" ({Formatters.fmt_duration(elapsed, precision=2)})"
            f"  {fields_str}\n"
        )
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line)

    @staticmethod
    def log_token_summary(
            results: List[RequestResult], *, output_dir: Optional[str] = None,
            network_tokens: Optional[List[NetworkTokenEntry]] = None,
            validation_events: Optional[List[ValidationEvent]] = None,
    ) -> None:
        """
        Log token usage summary to console, detail to file.

        When output_dir is provided, per-request lines go to
        server_tokens.log and only totals appear on the console.
        Without output_dir, per-request lines go to the console.

        :param results: Results of every request in the run
        :param output_dir: Directory for server_tokens.log, or None for console only
        :param network_tokens: Per-agent token entries parsed from the server log
        :param validation_events: Validation retry events parsed from the server log
        """
        has_tokens: bool = False
        for result in results:
            if result.get("total_tokens"):
                has_tokens = True
                break
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
    def _log_token_per_request(results: List[RequestResult]) -> None:
        """
        Log per-request token lines to the console.

        :param results: Results of every request in the run
        """
        for result in results:
            total: int = result.get("total_tokens", 0)
            if not total:
                continue
            prompt_tok: int = result.get("prompt_tokens", 0)
            comp_tok: int = result.get("completion_tokens", 0)
            llm_calls: int = result.get("llm_calls", 0)
            model: str = result.get("model", "unknown")
            rid: str = result.get("request_id", "?")
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
            results: List[RequestResult], output_dir: str, *,
            network_tokens: Optional[List[NetworkTokenEntry]] = None,
            validation_events: Optional[List[ValidationEvent]] = None,
    ) -> None:
        """
        Write per-request token detail to server_tokens.log.

        :param results: Results of every request in the run
        :param output_dir: Directory for server_tokens.log
        :param network_tokens: Per-agent token entries parsed from the server log
        :param validation_events: Validation retry events parsed from the server log
        """
        by_request: Dict[str, List[NetworkTokenEntry]] = TrafficRunner._group_network_tokens(
            network_tokens,
        )
        by_validation: Dict[str, ValidationEvent] = TrafficRunner._group_validation_events(
            validation_events,
        )
        path: str = os.path.join(output_dir, "server_tokens.log")
        with open(path, "w", encoding="utf-8") as fh:
            for result in results:
                total: int = result.get("total_tokens", 0)
                if not total:
                    continue
                TrafficRunner._write_token_request(
                    fh, result, by_request,
                    by_validation,
                )
        logger.info("  Detail:  %s", path)

    @staticmethod
    def _group_network_tokens(
            network_tokens: Optional[List[NetworkTokenEntry]],
    ) -> Dict[str, List[NetworkTokenEntry]]:
        """
        Group network token entries by request_id.

        :param network_tokens: Per-agent token entries parsed from the server log
        :return: request_id -> its token entries
        """
        by_request: Dict[str, List[NetworkTokenEntry]] = {}
        for entry in (network_tokens or []):
            rid: str = entry.get("request_id", "")
            by_request.setdefault(rid, []).append(entry)
        return by_request

    @staticmethod
    def _group_validation_events(
            validation_events: Optional[List[ValidationEvent]],
    ) -> Dict[str, ValidationEvent]:
        """
        Index validation events by request_id.

        :param validation_events: Validation retry events parsed from the server log
        :return: request_id -> its validation event
        """
        by_request: Dict[str, ValidationEvent] = {}
        for event in (validation_events or []):
            rid: str = event.get("request_id", "")
            by_request[rid] = event
        return by_request

    @staticmethod
    def _write_token_request(
            fh: TextIO, result: RequestResult,
            by_request: Dict[str, List[NetworkTokenEntry]],
            by_validation: Dict[str, ValidationEvent],
    ) -> None:
        """
        Write one request's token line with agent breakdown.

        :param fh: Open server_tokens.log
        :param result: The request's result
        :param by_request: request_id -> per-agent token entries
        :param by_validation: request_id -> validation event
        """
        rid: str = result.get("request_id", "?")
        total: int = result.get("total_tokens", 0)
        llm_calls: int = result.get("llm_calls", 0)
        model: str = result.get("model", "unknown")
        agent: str = result.get("reporting_agent", "")
        elapsed: float = result.get("elapsed", 0)
        status: str = result.get("status", "?")
        agent_suffix: str = ""
        if agent:
            agent_suffix = f", agent={agent}"
        fh.write(
            f"{rid}: {total:,} tokens, "
            f"{llm_calls} LLM call(s), "
            f"model={model}{agent_suffix}"
            f"  [{elapsed:.1f}s {status}]\n"
        )
        TrafficRunner._write_validation_detail(
            fh, rid, by_validation,
        )
        server_rid: str = result.get("server_request_id", rid)
        agents: List[NetworkTokenEntry] = (
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
            net: str = ag_entry.get("network", "?")
            a_calls: int = ag_entry.get("llm_calls", 0)
            a_total: int = ag_entry.get("total_tokens", 0)
            a_prompt: int = ag_entry.get("prompt_tokens", 0)
            a_comp: int = ag_entry.get("completion_tokens", 0)
            fh.write(
                f"  {net}: {a_calls} call(s)"
                f"  {a_total:,} tokens"
                f" ({a_prompt:,} prompt"
                f" / {a_comp:,} completion)\n"
            )
        if agents or agent or rid in by_validation:
            fh.write("\n")

    @staticmethod
    def _write_validation_detail(
            fh: TextIO, rid: str, by_validation: Dict[str, ValidationEvent],
    ) -> None:
        """
        Write per-request validation retry detail.

        :param fh: Open server_tokens.log
        :param rid: request_id of the request being written
        :param by_validation: request_id -> validation event
        """
        event: Optional[ValidationEvent] = by_validation.get(rid)
        if not event:
            return
        attempts: int = event.get("attempts", 0)
        fix_cycles: int = event.get("fix_cycles", 0)
        fh.write(
            f"  Validation: {attempts} attempt(s),"
            f" {fix_cycles} fix cycle(s)\n"
        )
        errors: List[str] = event.get("errors", [])
        for err in errors:
            fh.write(f"    - {err}\n")

    @staticmethod
    def _log_token_totals(results: List[RequestResult]) -> None:
        """
        Log aggregate token totals to the console.

        :param results: Results of every request in the run
        """
        total_tok: int = 0
        total_prompt: int = 0
        total_comp: int = 0
        count: int = 0
        for result in results:
            tok: int = result.get("total_tokens", 0)
            if not tok:
                continue
            total_tok += tok
            total_prompt += result.get("prompt_tokens", 0)
            total_comp += result.get("completion_tokens", 0)
            count += 1
        if count == 0:
            return
        avg: int = total_tok // count
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
            output_dir: Optional[str], request_id: int, stdout: str, stderr: str,
    ) -> None:
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
        stdout_path: str = os.path.join(
            requests_dir,
            f"request_{request_id}_stdout.txt",
        )
        with open(stdout_path, "w", encoding="utf-8") as fh:
            fh.write(stdout)
        if stderr and stderr.strip():
            stderr_path: str = os.path.join(
                requests_dir,
                f"request_{request_id}_stderr.txt",
            )
            with open(stderr_path, "w", encoding="utf-8") as fh:
                fh.write(stderr)
