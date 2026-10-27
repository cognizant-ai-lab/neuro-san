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
from concurrent.futures import Future
from concurrent.futures import ThreadPoolExecutor
from logging import Logger
from logging import getLogger
from threading import Event
from threading import Thread
from time import perf_counter
from time import time
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from psutil import Process

from neuro_san.message.processors.basic_message_processor import BasicMessageProcessor

from tests.load_tests.load_test_constants import LoadTestConstants
from tests.load_tests.monitoring.heartbeat import Heartbeat
from tests.load_tests.monitoring.server_log_monitor import ServerLogMonitor
from tests.load_tests.prompts.agent_profile import AgentProfile
from tests.load_tests.traffic.agent_request_executor import AgentRequestExecutor
from tests.load_tests.traffic.agent_request_result import AgentRequestResult
from tests.load_tests.traffic.output_parser import OutputParser
from tests.load_tests.traffic.request_recorder import RequestRecorder
from tests.load_tests.traffic.request_result_collector import RequestResultCollector
from tests.load_tests.traffic.request_status_policy import RequestStatusPolicy
from tests.load_tests.traffic.response_checker import ResponseChecker
from tests.load_tests.traffic.stage_plan import StagePlan


class TrafficRunner:
    """
    Fires concurrent requests via a thread pool and collects results.

    ResponseChecker checks each response, and RequestRecorder saves and logs each result.

    Holds the parsed CLI args and the agent profile so that callers
    do not need to thread them through every method.
    """

    def __init__(self, args: Namespace, profile: AgentProfile, cancel_event: Event) -> None:
        """
        Constructor.

        :param args: Parsed load-test command line
        :param profile: Prompts and response checks for the agent under test
        :param cancel_event: Set by the Ctrl-C handler to stop a stage early
        """
        self.logger: Logger = getLogger(self.__class__.__name__)
        self._args: Namespace = args
        self._profile: AgentProfile = profile
        self._executor: AgentRequestExecutor = AgentRequestExecutor()
        self._cancel_event: Event = cancel_event
        self._response_checker: ResponseChecker = ResponseChecker(profile)
        self._request_recorder: RequestRecorder = RequestRecorder(args)

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
        start_unix_seconds: float = time()
        start_seconds: float = perf_counter()
        request_settings: Dict[str, Any] = self._request_settings()
        request_result: AgentRequestResult = self._executor.execute_request(request_settings, prompt)
        elapsed_seconds: float = perf_counter() - start_seconds
        status: str = request_result.get_status()
        failure_reason: Optional[str] = self._failure_reason(request_result, global_request_id)
        if status == LoadTestConstants.STATUS_CREATED and failure_reason:
            status = LoadTestConstants.STATUS_FAILED
        time_to_first_response_seconds: float = request_result.get_time_to_first_response_seconds()
        end_unix_seconds: float = start_unix_seconds + elapsed_seconds
        result: Dict[str, Any] = {
            "request_id": f"request-{request_id}",
            "status": status,
            "elapsed": elapsed_seconds,
            "time_to_first_response": time_to_first_response_seconds,
            "start_time": start_unix_seconds,
            "end_time": end_unix_seconds,
            "prompt": prompt,
            "failure_reason": failure_reason,
            "error": None,
        }
        if status != LoadTestConstants.STATUS_CREATED:
            result["error"] = failure_reason
        self._request_recorder.record_request(request_id, output_dir, request_result, result)
        return result

    def run_stage(self, plan: StagePlan, server_process: Optional[Process] = None,
                  client_process: Optional[Process] = None,
                  log_monitor: Optional[ServerLogMonitor] = None) -> Dict[str, Any]:
        """
        Fire the stage's requests concurrently using a thread pool.

        When the Ctrl-C cancel_event becomes set, the stage returns early
        with whatever completed so far, marking the remainder KILLED.

        :param plan: Request count, pool size, request numbering and output directory of the stage
        :param server_process: Server process for the heartbeat's resource readings, or None
        :param client_process: Client process for the heartbeat's resource readings, or None
        :param log_monitor: Server log reader for server-side request timing, or None
        :return: Dict with "total_time_seconds", "results" (one dict per request), "peak_server_threads",
            "peak_client_rss_megabytes", "peak_server_rss_megabytes", "peak_system_memory" (dict with
            "memory_percent" and "available_gigabytes"), "peak_system_cpu_percent", "peak_system_threads",
            "server_died" and "interrupted" (bools); each peak is None when not measured
        """
        results_list: List[Dict[str, Any]] = []
        heartbeat_events: Dict[str, Event] = TrafficRunner._new_heartbeat_events()
        start_seconds: float = perf_counter()
        interrupted: bool = False
        heartbeat: Optional[Heartbeat] = None
        heartbeat_thread: Optional[Thread] = None
        # Not using ``with`` so that on Ctrl-C we can shut the pool
        # down without blocking on stalled worker threads (e.g.
        # in-thread HTTP requests that cannot be force-killed).
        pool: ThreadPoolExecutor = TrafficRunner._create_pool(plan)
        try:
            futures_ref: List[Future] = []
            heartbeat = self._create_heartbeat(server_process, client_process, plan, log_monitor)
            heartbeat_thread = TrafficRunner._start_heartbeat_thread(heartbeat, futures_ref, plan, start_seconds,
                                                                     heartbeat_events)
            TrafficRunner._wait_for_event(heartbeat_events, "ready_event")
            self._submit_requests(pool, plan, futures_ref, heartbeat)
            TrafficRunner._set_event(heartbeat_events, "fires_done_event")
            collector: RequestResultCollector = RequestResultCollector(futures_ref, results_list, start_seconds)
            interrupted = collector.collect_with_timeout(self._args.stage_timeout, self._cancel_event)
        finally:
            TrafficRunner._set_event(heartbeat_events, "stop_event")
            if heartbeat_thread is not None:
                heartbeat_thread.join(timeout=LoadTestConstants.THREAD_JOIN_TIMEOUT_SECONDS)
            pool.shutdown(wait=not interrupted, cancel_futures=True)
        total_time_seconds: float = perf_counter() - start_seconds
        # The heartbeat thread was joined above, so its peaks are final.
        return TrafficRunner._build_stage_result(total_time_seconds, results_list, heartbeat,
                                                 heartbeat_events, interrupted)

    def _request_settings(self) -> Dict[str, Any]:
        """
        Build the connection settings of one request from the CLI arguments.

        :return: The settings AgentRequestExecutor.execute_request() takes
        """
        chat_filter_type: str = self._args.chat_filter.upper()
        request_settings: Dict[str, Any] = {
            "host": self._args.host,
            "port": self._args.port,
            "agent": self._args.agent,
            "timeout_seconds": self._args.request_timeout,
            "idle_timeout_seconds": self._args.idle_timeout,
            "use_https": self._args.https,
            "chat_filter_type": chat_filter_type,
        }
        return request_settings

    @staticmethod
    def _wait_for_event(heartbeat_events: Dict[str, Event], name: str) -> None:
        """
        Block until one heartbeat event is set.

        :param heartbeat_events: The stage's heartbeat events, by name
        :param name: Name of the event to wait for
        """
        event: Event = heartbeat_events.get(name)
        event.wait()

    @staticmethod
    def _set_event(heartbeat_events: Dict[str, Event], name: str) -> None:
        """
        Set one heartbeat event.

        :param heartbeat_events: The stage's heartbeat events, by name
        :param name: Name of the event to set
        """
        event: Event = heartbeat_events.get(name)
        event.set()

    def _run_one_tracked(self, request_id: int, global_request_id: int, output_dir: Optional[str],
                         heartbeat: Heartbeat) -> Dict[str, Any]:
        """
        Run one request and count it on the heartbeat when it fails.

        :param request_id: Request number within the current stage
        :param global_request_id: Request number across the whole run
        :param output_dir: Directory for per-request output files, or None
        :param heartbeat: Counts the failed requests for the progress line
        :return: The request result
        """
        result: Dict[str, Any] = self.run_one_http(request_id, global_request_id, output_dir)
        if result.get("status") != LoadTestConstants.STATUS_CREATED:
            heartbeat.count_failed_request()
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
        if status == LoadTestConstants.STATUS_CREATED:
            processor: Optional[BasicMessageProcessor] = request_result.get_processor()
            response_checks: Dict[str, Any] = self._profile.get_response(global_request_id,
                                                                         same_prompt=self._args.same_prompt)
            return self._response_checker.check_response(processor, response_checks)
        failure_reason: Optional[str] = request_result.get_failure_reason()
        if failure_reason:
            return failure_reason
        if status != LoadTestConstants.STATUS_FAILED:
            return None
        if not RequestStatusPolicy.is_traceback(status, response_text):
            return "empty response from agent"
        return OutputParser.last_stderr_line(response_text)

    @staticmethod
    def _build_stage_result(total_time_seconds: float, results_list: List[Dict[str, Any]], heartbeat: Heartbeat,
                            heartbeat_events: Dict[str, Event], interrupted: bool) -> Dict[str, Any]:
        """
        Put the stage's timing, results and heartbeat peaks together in the dict run_stage() returns.

        :param total_time_seconds: Seconds the stage took
        :param results_list: One result per request
        :param heartbeat: The stage's heartbeat, already joined
        :param heartbeat_events: The stage's heartbeat events; "server_dead_event" is set when the heartbeat
            found the server process dead
        :param interrupted: True when Ctrl-C stopped the stage
        :return: The run_stage() result; its docstring lists the keys
        """
        server_dead_event: Event = heartbeat_events.get("server_dead_event")
        stage_result: Dict[str, Any] = {
            "total_time_seconds": total_time_seconds,
            "results": results_list,
            "peak_server_threads": heartbeat.get_peak_server_threads(),
            "peak_client_rss_megabytes": heartbeat.get_peak_client_rss_megabytes(),
            "peak_server_rss_megabytes": heartbeat.get_peak_server_rss_megabytes(),
            "peak_system_memory": heartbeat.get_peak_system_memory(),
            "peak_system_cpu_percent": heartbeat.get_peak_system_cpu_percent(),
            "peak_system_threads": heartbeat.get_peak_system_threads(),
            "server_died": server_dead_event.is_set(),
            "interrupted": interrupted,
        }
        return stage_result

    @staticmethod
    def _new_heartbeat_events() -> Dict[str, Any]:
        """
        Create the events that Heartbeat.progress_heartbeat() uses during a stage.

        :return: The events argument of Heartbeat.progress_heartbeat(), keyed by event name
        """
        heartbeat_events: Dict[str, Event] = {}
        event_name: str
        # One new event per event that Heartbeat.progress_heartbeat() reads.
        for event_name in ("stop_event", "ready_event", "fires_done_event", "server_dead_event"):
            heartbeat_events[event_name] = Event()
        return heartbeat_events

    def _create_heartbeat(self, server_process: Optional[Process], client_process: Optional[Process],
                          plan: StagePlan, log_monitor: Optional[ServerLogMonitor]) -> Heartbeat:
        """
        Create the stage's Heartbeat, reading the server log from its current end.

        :param server_process: Server process for resource readings, or None
        :param client_process: Client process for resource readings, or None
        :param plan: The stage plan; its output directory receives progress.log, when set
        :param log_monitor: Server log reader for server-side request timing, or None
        :return: The Heartbeat
        """
        log_start_position: Optional[int] = None
        if log_monitor is not None:
            log_start_position = log_monitor.read_position()
        output_dir: Optional[str] = plan.get_output_dir()
        primary_start_pattern: str = self._profile.get_primary_start_pattern()
        server_log_timing: Dict[str, Any] = {
            "log_monitor": log_monitor,
            "log_start_position": log_start_position,
            "primary_start_pattern": primary_start_pattern,
        }
        heartbeat: Heartbeat = Heartbeat(server_process, client_process, output_dir, server_log_timing)
        return heartbeat

    @staticmethod
    def _create_pool(plan: StagePlan) -> ThreadPoolExecutor:
        """
        Create the thread pool that runs the stage's requests.

        :param plan: The stage plan, for its pool size
        :return: The thread pool, sized to the plan's max workers
        """
        max_workers: int = plan.get_max_workers()
        pool: ThreadPoolExecutor = ThreadPoolExecutor(max_workers=max_workers)
        return pool

    @staticmethod
    def _start_heartbeat_thread(heartbeat: Heartbeat, futures_ref: List[Future], plan: StagePlan,
                                start_seconds: float, heartbeat_events: Dict[str, Event]) -> Thread:
        """
        Start the daemon thread that runs Heartbeat.progress_heartbeat() during the stage.

        :param heartbeat: The stage's heartbeat
        :param futures_ref: The stage's request futures; the heartbeat reads it while requests run
        :param plan: The stage plan, for its request count
        :param start_seconds: perf_counter() at the start of the stage
        :param heartbeat_events: The events from _new_heartbeat_events()
        :return: The started thread
        """
        num_requests: int = plan.get_num_requests()
        heartbeat_thread: Thread = Thread(target=heartbeat.progress_heartbeat,
                                          args=[futures_ref, num_requests, start_seconds, heartbeat_events],
                                          daemon=True)
        heartbeat_thread.start()
        return heartbeat_thread

    def _submit_requests(self, pool: ThreadPoolExecutor, plan: StagePlan, futures: List[Future],
                         heartbeat: Heartbeat) -> None:
        """
        Submit every request of the stage to the pool.

        :param pool: Thread pool of the stage
        :param plan: Request count, request numbering and output directory of the stage
        :param futures: Receives one future per request; the heartbeat reads it while requests run
        :param heartbeat: Counts the failed requests for the progress line
        """
        index: int
        # Submit one tracked request per planned request.
        for index in range(plan.get_num_requests()):
            future: Future = pool.submit(self._run_one_tracked, index + 1, plan.get_global_offset() + index,
                                         plan.get_output_dir(), heartbeat)
            futures.append(future)
