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
from functools import partial
from inspect import cleandoc
from logging import INFO
from logging import Logger
from logging import basicConfig
from logging import getLogger
from os import _exit
from signal import SIGINT
from signal import getsignal
from signal import signal
from sys import stderr
from sys import stdout
from threading import Event
from types import FrameType
from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional
from typing import Union

from psutil import Process

from tests.load_tests.load_test_constants import LoadTestConstants
from tests.load_tests.load_test_arguments import LoadTestArguments
from tests.load_tests.monitoring.server_log_monitor import ServerLogMonitor
from tests.load_tests.monitoring.server_only_monitor import ServerOnlyMonitor
from tests.load_tests.prompts.agent_profile import AgentProfile
from tests.load_tests.prompts.agent_profile_factory import AgentProfileFactory
from tests.load_tests.reporting.cross_run_comparison import CrossRunComparison
from tests.load_tests.reporting.history_recorder import HistoryRecorder
from tests.load_tests.reporting.results_rebuilder import ResultsRebuilder
from tests.load_tests.reporting.disconnection_reporter import DisconnectionReporter
from tests.load_tests.reporting.latency_analyzer import LatencyAnalyzer
from tests.load_tests.reporting.pool_analyzer import PoolAnalyzer
from tests.load_tests.reporting.resource_reporter import ResourceReporter
from tests.load_tests.reporting.run_output_writer import RunOutputWriter
from tests.load_tests.reporting.summary import SummaryReporter
from tests.load_tests.reporting.trend_history import TrendHistory
from tests.load_tests.traffic.runner import TrafficRunner
from tests.load_tests.traffic.stage_executor import StageExecutor
from tests.load_tests.validation.environment_validator import EnvironmentValidator
from tests.load_tests.validation.input_validator import InputValidator
from tests.load_tests.validation.load_test_abort_error import LoadTestAbortError
from tests.load_tests.validation.server_checker import ServerChecker


class LoadTestCli:  # pylint: disable=too-many-instance-attributes
    """
    Runs the full load test workflow for neuro-san agent networks.

    See tests/load_tests/load_tests.md for prerequisites, test levels, and
    usage examples.
    """

    LOGGER: Logger = getLogger(__name__)

    def __init__(self, args: Namespace) -> None:
        """
        Initialize the load test CLI with parsed arguments.

        :param args: Parsed command-line arguments
        """
        self.args: Namespace = args
        self.input_validator = InputValidator(args)
        self.hocon_files: List[str] = self.input_validator.validate_fixtures_hocon_dir()
        self.profile: AgentProfile = AgentProfileFactory().create(
            args.agent, args.profile_path, args.project_root,
            hocon_files=self.hocon_files,
        )
        self.server_process: Optional[Process] = None
        self.server_log: Optional[str] = args.server_log
        self.log_monitor: Optional[ServerLogMonitor] = None
        if self.server_log:
            self.log_monitor = ServerLogMonitor(self.server_log)
        self._cancel_event: Event = Event()
        self.runner: TrafficRunner = TrafficRunner(args, self.profile, self._cancel_event)
        self.resource_reporter = ResourceReporter()
        self.probe_result: Optional[Dict[str, Any]] = None
        self._aborted: bool = False
        self._interrupted: bool = False
        self.server_checker: ServerChecker = ServerChecker(args)
        output_parts: Dict[str, Any] = {
            "server_checker": self.server_checker,
            "profile": self.profile,
            "hocon_files": self.hocon_files,
            "resource_reporter": self.resource_reporter,
        }
        self._output_writer: RunOutputWriter = RunOutputWriter(args, output_parts)
        output_base: str = self._output_writer.output_base()
        self._history_recorder: HistoryRecorder = HistoryRecorder(args, output_base)

    def run(self) -> int:
        """
        Execute the full load test workflow.

        :return: The exit code: 0 when every request passes or the server-only monitor exits at its prompt,
                 1 on failures or an abort, 2 on Ctrl-C
        :raises SystemExit: When the arguments don't fit together
        :raises LoadTestAbortError: When the server can't be reached or the --server-log file is not found
        """
        level: str = self._check_mode_args()
        stale_log_age_minutes: Optional[int] = self.server_checker.validate_server_log()

        stages: List[int] = self.input_validator.resolve_stages()
        total_cap: int = self.input_validator.resolve_max_requests(stages)

        self._output_writer.setup_test_log()
        if not self.args.server_only:
            self.server_checker.preflight_server_check()
            output_dir: Optional[str] = self._output_writer.get_output_dir()
            self.probe_result = self.input_validator.confirm_cost(stages, total_cap, runner=self.runner,
                                                                  output_dir=output_dir,
                                                                  stale_log_age_minutes=stale_log_age_minutes)

        is_local: bool = self.args.host in LoadTestConstants.LOCAL_HOSTS
        self._find_server(is_local)
        if self.args.server_only:
            return self._run_server_only()

        if not is_local:
            LoadTestCli.LOGGER.info("Remote mode: targeting %s:%s", self.args.host, self.args.port)
            LoadTestCli.LOGGER.info("  Process monitoring disabled (server is not local)")

        # Server-only runs return above, so only --client-only is left of the split modes here.
        monitor_resources: bool = level != LoadTestConstants.LEVEL_MIN or self.args.client_only
        self._log_run_config(level, stages, total_cap, monitor_resources)
        run_inputs: Dict[str, Any] = {
            "stages": stages,
            "total_cap": total_cap,
            "monitor_resources": monitor_resources,
            "has_server_log": self.server_log is not None,
            "probe_result": self.probe_result,
        }
        exit_code: int = self._run_stages(level, run_inputs)
        return exit_code

    def was_interrupted(self) -> bool:
        """
        Return True if the run was stopped early by Ctrl-C.

        :return: True when Ctrl-C stops the run
        """
        return self._interrupted

    @staticmethod
    def main() -> None:
        """
        Entry point for the load test script.
        """
        basicConfig(level=INFO, format="%(message)s")
        epilog: str = cleandoc(LoadTestCli.__doc__)
        args: Namespace = LoadTestArguments.parse_args(epilog)
        if args.rebuild:
            ResultsRebuilder(args.rebuild, force=args.rebuild_all).run()
            return
        if args.trend:
            trend_agent_filter: Optional[List[str]] = LoadTestCli._agent_filter(args)
            TrendHistory(args.trend, agent_filter=trend_agent_filter).run()
            return
        if args.compare:
            agent_filter: Optional[List[str]] = LoadTestCli._agent_filter(args)
            run_filter: Optional[List[str]] = None
            if args.compare_runs:
                run_filter = []
                run_name: str
                # Keep each comma-separated run name, without its spaces.
                for run_name in args.compare_runs.split(","):
                    run_filter.append(run_name.strip())
            CrossRunComparison(
                args.compare,
                agent_filter=agent_filter,
                baseline_requests=args.compare_baseline,
                run_filter=run_filter,
            ).run()
            return
        load_test_cli: Optional[LoadTestCli] = None
        exit_code: int = 0
        try:
            load_test_cli = LoadTestCli(args)
            exit_code = load_test_cli.run()
        except LoadTestAbortError as abort_error:
            abort_exit_code: int = abort_error.get_exit_code()
            raise SystemExit(abort_exit_code) from abort_error
        if load_test_cli.was_interrupted():
            # After Ctrl-C some worker threads (e.g. un-killable
            # in-thread HTTP requests) may still be blocked.  Results
            # are already printed and saved, so exit hard rather than
            # hang joining those threads at interpreter shutdown.
            stdout.flush()
            stderr.flush()
            _exit(exit_code)
        raise SystemExit(exit_code)

    def _check_mode_args(self) -> str:
        """
        Check that the mode arguments fit together, fill in the server log and level defaults,
        then validate the agent name and the environment.

        :return: The test level
        :raises SystemExit: When the arguments don't fit together
        """
        level: str = self.args.level
        self.args.include_tokens = not self.args.no_tokens
        split_mode: bool = self.args.client_only or self.args.server_only
        if split_mode:
            level = LoadTestConstants.LEVEL_MIN
            self.args.level = LoadTestConstants.LEVEL_MIN
        elif level == LoadTestConstants.LEVEL_MIN:
            LoadTestCli.LOGGER.error(
                "--level min requires --client-only or "
                "--server-only. For an all-in-one run use "
                "--level norm or --level adv.",
            )
            raise SystemExit(1)
        if self.args.client_only and self.args.server_only:
            LoadTestCli.LOGGER.error("--client-only and --server-only are mutually exclusive.")
            raise SystemExit(1)
        if self.args.client_only and self.args.server_log is not None:
            LoadTestCli.LOGGER.error("--client-only cannot be used with --server-log (server log is remote).")
            raise SystemExit(1)
        if self.args.server_only and self.args.server_log is None:
            self.args.server_log = "auto"
        if self.args.no_server_log and not self.args.server_only:
            self.args.server_log = None
        elif (self.args.server_log is None
                and not self.args.client_only
                and not self.args.server_only
                and self.args.host in LoadTestConstants.LOCAL_HOSTS
                and level != LoadTestConstants.LEVEL_MIN):
            self.args.server_log = EnvironmentValidator.try_auto_detect_server_log(self.args)
        if (level != LoadTestConstants.LEVEL_MIN
                and not self.args.client_only
                and not self.args.server_only
                and not self.args.no_server_log
                and self.args.server_log is None):
            if self.args.host not in LoadTestConstants.LOCAL_HOSTS:
                LoadTestCli.LOGGER.error(
                    "--level %s needs a local server to read "
                    "server.log. Use --client-only for a remote "
                    "server, or pass --server-log <path>.",
                    level,
                )
                raise SystemExit(1)
            self.server_checker.confirm_no_server_log(level)
        LoadTestArguments.apply_level_defaults(self.args, self.args.explicit_args)
        LoadTestArguments.apply_scale(self.args)
        self.input_validator.validate_agent_name()
        EnvironmentValidator.validate_environment()
        return level

    def _find_server(self, is_local: bool) -> None:
        """
        Find the local server process and resolve an "auto" --server-log path.

        :param is_local: True when the server host is local
        """
        if self.args.client_only:
            LoadTestCli.LOGGER.info("Client-only mode: skipping server process detection.")
        elif self.args.server_only:
            self.server_process = EnvironmentValidator.find_local_server(self.args)
        elif is_local:
            self.server_process = EnvironmentValidator.find_local_server(self.args)

        if self.args.server_log == "auto":
            self.args.server_log = EnvironmentValidator.auto_detect_server_log(self.server_process)

        self.server_log = self.args.server_log
        if self.server_log:
            self.log_monitor = ServerLogMonitor(self.server_log)

    def _run_server_only(self) -> int:
        """
        Log the server-only config and run the server-only monitor.

        :return: The exit code of the server-only monitor
        """
        LoadTestCli.LOGGER.info(
            "\nConfig: agent=%s, mode=server-only, "
            "num_requests=%s, host=%s, port=%s, "
            "stage_timeout=%ss",
            self.args.agent, self.args.num_requests,
            self.args.host, self.args.port,
            self.args.stage_timeout,
        )
        if self.server_log:
            LoadTestCli.LOGGER.info("  server_log=%s", self.server_log)
        output_base: str = self._output_writer.output_base()
        monitor_parts: Dict[str, Any] = {
            "server_process": self.server_process,
            "log_monitor": self.log_monitor,
            "history_recorder": self._history_recorder,
            "server_checker": self.server_checker,
        }
        server_only_monitor: ServerOnlyMonitor = ServerOnlyMonitor(self.args, self.profile, monitor_parts)
        return server_only_monitor.run(output_base)

    def _log_run_config(self, level: str, stages: List[int], total_cap: int, monitor_resources: bool) -> None:
        """
        Log the config of the run.

        :param level: The test level
        :param stages: Request count of each stage, in order
        :param total_cap: Most requests to send in the whole test
        :param monitor_resources: True when resource snapshots are taken around each stage
        """
        prompt_mode: str = "varied"
        if self.args.same_prompt:
            prompt_mode = "same"
        if self.args.allow_caching:
            prompt_mode = f"{prompt_mode} (caching allowed)"
        mode: str = "flat"
        if self.args.ramp:
            mode = "ramp"
        profile_source: str = self._output_writer.profile_source()
        LoadTestCli.LOGGER.info(
            "\nConfig: agent=%s, mode=%s, level=%s, "
            "stages=%s, rounds=%s, max_requests=%s, host=%s, port=%s, "
            "timeout=%ss, idle_timeout=%ss, "
            "stage_timeout=%ss, prompt_mode=%s, profile_source=%s",
            self.args.agent, mode, level, stages,
            self.args.num_rounds, total_cap,
            self.args.host, self.args.port, self.args.request_timeout,
            self.args.idle_timeout, self.args.stage_timeout,
            prompt_mode, profile_source,
        )
        if monitor_resources:
            LoadTestCli.LOGGER.info("  settle_time=%ss", self.args.settle_time)
        if self.server_log:
            LoadTestCli.LOGGER.info("  server_log=%s", self.server_log)
        else:
            LoadTestCli.LOGGER.info("  server_log=none")
        probe_tokens: Optional[int] = None
        if self.probe_result:
            probe_tokens = self.probe_result.get("total_tokens")
        estimated_tokens: Optional[int] = self.profile.get_estimated_tokens_per_request()
        if probe_tokens:
            LoadTestCli.LOGGER.info("  tokens_per_request=%s (measured by probe)", f"{probe_tokens:,}")
        elif estimated_tokens:
            LoadTestCli.LOGGER.info("  estimated_tokens_per_request=%s", f"{estimated_tokens:,}")

    def _run_stages(self, level: str, run_inputs: Dict[str, Any]) -> int:
        """
        Run the stages, log the results, and save the output files, also after Ctrl-C.

        :param level: The test level
        :param run_inputs: The run_inputs dict of StageExecutor.run_all_stages()
        :return: The exit code: 0 when every request passes, 1 on failures or an abort, 2 on Ctrl-C
        """
        stage_summaries: List[Dict[str, Any]] = []
        exit_code: int = 1
        pre_test_log_position: Optional[int] = None
        if self.server_log:
            pre_test_log_position = self.log_monitor.read_position()
        executor_parts: Dict[str, Any] = {
            "profile": self.profile,
            "log_monitor": self.log_monitor,
            "resource_reporter": self.resource_reporter,
            "server_process": self.server_process,
            "output_dir": self._output_writer.get_output_dir(),
        }
        stage_executor: StageExecutor = StageExecutor(self.args, self.runner, executor_parts)
        prev_sigint_handler: Optional[Union[Callable, int]] = self._install_interrupt_handler()
        try:
            stages_outcome: Dict[str, Any] = stage_executor.run_all_stages(run_inputs)
            stage_summaries = stages_outcome.get("stage_summaries")
            self._aborted = stages_outcome.get("aborted")
            if stages_outcome.get("interrupted"):
                self._interrupted = True

            if self._interrupted:
                LoadTestCli.LOGGER.warning(
                    "\n  Test interrupted (Ctrl-C) — the results "
                    "below cover only the requests that completed "
                    "before the interrupt.",
                )

            self._log_results(stage_summaries)

            server_chat_timing: List[Dict[str, object]] = []
            if self.server_log and pre_test_log_position is not None:
                server_chat_timing = self.log_monitor.parse_streaming_chat_timing_since(pre_test_log_position)

            monitor_resources: bool = run_inputs.get("monitor_resources")
            self._log_server_analysis(level, stage_summaries, monitor_resources)

            if self._interrupted:
                exit_code = 2
            elif not self._aborted:
                exit_code = self._check_results(stage_summaries)
            self._output_writer.export_raw_json(stage_summaries, exit_code=exit_code)
            self._output_writer.maybe_write_summary(stage_summaries, server_chat_timing)
            if self._interrupted:
                self._output_writer.rename_interrupted()
        except KeyboardInterrupt:
            LoadTestCli.LOGGER.info("\n  Interrupted — saving partial results...")
            self._output_writer.export_raw_json(stage_summaries, exit_code=2)
            self._output_writer.rename_interrupted()
            exit_code = 2
        finally:
            if prev_sigint_handler is not None:
                signal(SIGINT, prev_sigint_handler)
            server_ns_version: Optional[str] = self.server_checker.get_server_ns_version()
            self._history_recorder.append_client_record(stage_summaries, server_ns_version)
            self._output_writer.finalize_test_log(stage_summaries, self._history_recorder)

        return exit_code

    def _log_results(self, stage_summaries: List[Dict[str, Any]]) -> None:
        """
        Log the ramp summary, the overall results and the latency analysis.

        :param stage_summaries: One summary dict per stage
        """
        neuro_san_version: Optional[str] = self.server_checker.resolve_ns_version()
        summary_reporter: SummaryReporter = SummaryReporter(
            stage_summaries,
            neuro_san_version=neuro_san_version,
            client_token_source="HTTP token_accounting",
        )
        if len(stage_summaries) > 1:
            summary_reporter.log_ramp_summary(is_ramp=self.args.ramp)

        summary_reporter.log_overall_results()

        latency_analyzer: LatencyAnalyzer = LatencyAnalyzer(stage_summaries)
        latency_analyzer.log_latency_analysis(is_ramp=self.args.ramp)
        latency_analyzer.log_degradation(is_ramp=self.args.ramp)

    def _log_server_analysis(self, level: str, stage_summaries: List[Dict[str, Any]], monitor_resources: bool) -> None:
        """
        Log the resource and disconnection analysis, and the pool reuse analysis at the adv level.

        :param level: The test level
        :param stage_summaries: One summary dict per stage
        :param monitor_resources: True when resource snapshots are taken around each stage
        """
        if monitor_resources:
            total_client_requests: int = 0
            total_server_calls: int = 0
            stage_summary: Dict[str, Any]
            # Add up the client requests and server calls of every stage.
            for stage_summary in stage_summaries:
                total_client_requests += stage_summary.get("concurrent", 0)
                started_count: Optional[int] = stage_summary.get("total_started")
                if started_count:
                    total_server_calls += started_count

            self.resource_reporter.log_combined_analysis(total_client_requests, total_server_calls)
            disconnection_reporter: DisconnectionReporter = DisconnectionReporter(stage_summaries)
            disconnection_reporter.log_disconnection_summary()

        if level == LoadTestConstants.LEVEL_ADV:
            if self.server_log is not None:
                pool_analyzer: PoolAnalyzer = PoolAnalyzer(stage_summaries)
                pool_analyzer.log_pool_reuse_analysis()
            else:
                LoadTestCli.LOGGER.info("\n  Pool reuse analysis: not available (no --server-log)")

    def _install_interrupt_handler(self) -> Optional[Union[Callable, int]]:
        """
        Install a SIGINT handler that requests a graceful stop.

        The first Ctrl-C sets a cancel event so in-flight requests are
        killed and the completed ones are still summarized.  A second
        Ctrl-C restores the previous handler so the interpreter exits
        immediately.

        :return: The previous handler, or None if it could not be installed
                 (e.g. not on the main thread)
        """
        try:
            prev_handler: Optional[Union[Callable, int]] = getsignal(SIGINT)
            # partial() binds the previous handler, so the second Ctrl-C can put it back.
            sigint_handler: partial = partial(self._handle_sigint, prev_handler)
            signal(SIGINT, sigint_handler)
            return prev_handler
        except (ValueError, OSError):
            return None

    def _handle_sigint(self, prev_handler: Optional[Union[Callable, int]], _signum: int,
                       _frame: Optional[FrameType]) -> None:
        """
        Stop gracefully on the first Ctrl-C, and restore the previous handler on the second.

        :param prev_handler: SIGINT handler from before the load test, or None
        :param _signum: Signal number (not used)
        :param _frame: Current stack frame (not used)
        """
        if not self._cancel_event.is_set():
            self._cancel_event.set()
            self._interrupted = True
            LoadTestCli.LOGGER.warning(
                "\n  Ctrl-C received — stopping and gathering "
                "results for completed requests (press Ctrl-C "
                "again to force-quit)...",
            )
        elif prev_handler is not None:
            signal(SIGINT, prev_handler)

    def _check_results(self, stage_summaries: List[Dict[str, Any]]) -> int:
        """
        Log pass/fail verdict and return appropriate exit code.

        :param stage_summaries: One summary dict per stage
        :return: 0 when the test passes, 1 when it fails
        """
        all_results: List[Dict[str, Any]] = RunOutputWriter.collect_stage_results(stage_summaries)
        total: int = len(all_results)
        passed: int = 0
        result: Dict[str, Any]
        # Count the requests that passed.
        for result in all_results:
            if result.get("status") == LoadTestConstants.STATUS_CREATED:
                passed += 1
        failed: int = total - passed

        if failed > 0:
            LoadTestCli.LOGGER.info("\nLOAD TEST FAILED: %s/%s requests failed", failed, total)
            return 1

        LoadTestCli.LOGGER.info("\nLOAD TEST PASSED: all %s requests completed successfully", total)
        return 0

    @staticmethod
    def _agent_filter(args: Namespace) -> Optional[List[str]]:
        """
        Split --compare-agent into a list of agent names.

        :param args: Parsed command-line arguments
        :return: The agent names, or None when --compare-agent is not set
        """
        if not args.compare_agent:
            return None
        agent_names: List[str] = []
        name: str
        # Keep each comma-separated agent name, without its spaces.
        for name in args.compare_agent.split(","):
            agent_names.append(name.strip())
        return agent_names


if __name__ == "__main__":
    LoadTestCli.main()
