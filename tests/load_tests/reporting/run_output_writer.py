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

from getpass import getuser
from json import dump
from logging import Logger
from logging import getLogger
from platform import platform
from platform import python_version
from re import sub
from socket import gethostname
from tempfile import gettempdir
from os import getuid
from os import makedirs
from os import rename
from os.path import isdir
from os.path import isfile
from os.path import join
from time import strftime
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from leaf_common.logging.sensitive_logger import SensitiveLogger

from tests.load_tests.confirm import Confirm
from tests.load_tests.load_test_constants import LoadTestConstants
from tests.load_tests.reporting.formatters import Formatters
from tests.load_tests.reporting.history_recorder import HistoryRecorder
from tests.load_tests.reporting.json_metadata import JsonMetadata
from tests.load_tests.reporting.resource_reporter import ResourceReporter
from tests.load_tests.reporting.run_log import RunLog
from tests.load_tests.reporting.run_namer import RunNamer
from tests.load_tests.reporting.summary_file_writer import SummaryFileWriter
from tests.load_tests.validation.server_checker import ServerChecker


class RunOutputWriter:
    """
    Writes the output files of one load-test run: the run directory and its stdout.log, raw_results.json,
    summary.txt, and the OUTPUT FILES list at the end of the run.
    """

    # Keys of the "config" section of raw_results.json, in file order.
    CONFIG_KEYS: List[str] = [
        "agent",
        "profile_path",
        "level",
        "mode",
        "host",
        "port",
        "request_timeout",
        "idle_timeout",
        "stage_timeout",
        "total_timeout",
        "settle_time",
        "max_workers",
        "num_rounds",
        "num_requests",
        "same_prompt",
        "allow_caching",
        "profile_source",
        "fixtures_hocon_dir",
        "hocon_files",
        "chat_filter",
        "server_log",
        "estimated_tokens_per_request",
    ]
    # raw_results.json keeps main's names for these keys (json_metadata.py gives their unit); run_settings names them
    # with the unit.
    CONFIG_SETTINGS_KEYS: Dict[str, str] = {
        "request_timeout": "request_timeout_seconds",
        "idle_timeout": "idle_timeout_seconds",
        "stage_timeout": "stage_timeout_seconds",
        "total_timeout": "total_timeout_seconds",
        "settle_time": "settle_time_seconds",
    }

    def __init__(self, run_settings: Dict[str, Any], output_parts: Dict[str, Any]) -> None:
        """
        Keep the run's arguments and the parts the output files are built from.

        :param run_settings: A dict with the settled command-line values of the run; a missing key reads as None:
            "agent"                    --agent: the agent network under test
            "allow_caching"            True with --allow-caching
            "chat_filter"              --chat-filter value
            "fixtures_hocon_dir"       --fixtures-hocon-dir path, or None
            "host"                     --host: the server host
            "idle_timeout_seconds"     --idle-timeout: seconds a request may stay silent
            "level"                    --level, after the level defaults
            "max_workers"              --max-workers: most concurrent requests
            "no_dry_run"               True with --no-dry-run
            "num_requests"             --num-requests: requests of a flat stage
            "num_rounds"               --num-rounds: rounds of each stage
            "output_dir"               --output-dir path, or None
            "port"                     --port: the server port
            "profile_path"             --profile-path, or None
            "ramp"                     True with --ramp
            "request_timeout_seconds"  --request-timeout: seconds a request may take
            "same_prompt"              True with --same-prompt
            "server_log"               --server-log path ("auto" until LoadTestCli resolves it), or None
            "settle_time_seconds"      --settle-time: seconds to wait after each stage
            "stage_timeout_seconds"    --stage-timeout: seconds a stage may take
            "total_timeout_seconds"    --total-timeout: seconds the whole test may take, 0 for none
        :param output_parts: A dict with the following keys:
            "server_checker"     The ServerChecker
            "hocon_files"        Fixture HOCON file paths
            "resource_reporter"  The ResourceReporter
        """
        self.logger: Logger = getLogger(self.__class__.__name__)
        self.confirm: Confirm = Confirm()
        # A dict, not one member per value: the constructor docstring lists the keys this class reads.
        self._run_settings: Dict[str, Any] = run_settings
        # A dict, not one member per value: the constructor docstring lists the keys this class reads.
        self._output_parts: Dict[str, Any] = output_parts
        self._run_log: RunLog = RunLog()
        self._output_dir: Optional[str] = None

    def set_server_log(self, server_log: Optional[str]) -> None:
        """
        Keep the --server-log path once LoadTestCli has resolved "auto".

        :param server_log: The resolved --server-log path, or None
        """
        self._run_settings["server_log"] = server_log

    def get_output_dir(self) -> Optional[str]:
        """
        Return the run's output directory.

        :return: The output directory, or None before setup_test_log() creates it
        """
        return self._output_dir

    def get_resource_reporter(self) -> ResourceReporter:
        """
        :return: The ResourceReporter of the run
        """
        resource_reporter: ResourceReporter = self._output_parts.get("resource_reporter")
        return resource_reporter

    def profile_source(self) -> str:
        """
        Describe where the profile came from, for logs and raw_results.json.

        :return: "hocon (<N> files)" or "json profile"
        """
        hocon_files: List[str] = self._output_parts.get("hocon_files")
        if hocon_files:
            return f"hocon ({len(hocon_files)} files)"
        return "json profile"

    def output_base(self) -> str:
        """
        Return the base output directory.

        The default is per-user because the temp directory is shared:
        whoever ran first would otherwise own ``load_test`` and lock
        everyone else out of it.

        :return: Path of the base output directory
        """
        output_dir: Optional[str] = self._run_settings.get("output_dir")
        if output_dir:
            return output_dir
        try:
            user: str = getuser()
        except (KeyError, OSError):
            # No passwd entry for this uid (some containers).
            user_id: int = getuid()
            user = str(user_id)
        # Replace each character that is not a letter, digit, ".", "_" or "-" with "_",
        # so a domain name such as "CORP\alice" stays one folder: "CORP_alice".
        user = sub(r"[^A-Za-z0-9._-]", "_", user)
        temp_dir: str = gettempdir()
        output_base: str = join(temp_dir, f"load_test_{user}")
        return output_base

    def setup_test_log(self) -> None:
        """
        Create output directory and add a file handler for logging.
        """
        server_checker: ServerChecker = self._output_parts.get("server_checker")
        timestamp: str = strftime("%Y%m%d_%H%M%S")
        base: str = self.output_base()
        neuro_san_version: Optional[str] = server_checker.resolve_ns_version()
        request_count: int = self._run_settings.get("num_requests")
        host: str = self._run_settings.get("host")
        folder_name: str = RunNamer.run_folder_name(timestamp, host, neuro_san_version, request_count)
        level: str = self._run_settings.get("level")
        self._output_dir = join(base, level, folder_name)
        makedirs(self._output_dir, exist_ok=True)
        self._run_log.open(self._output_dir)

    def export_raw_json(self, stage_summaries: List[Dict[str, Any]], exit_code: int,
                        estimated_tokens_per_request: Optional[int]) -> None:
        """
        Save all test data as a single raw_results.json file.

        :param stage_summaries: One summary dict per stage
        :param exit_code: Exit code of the test
        :param estimated_tokens_per_request: The agent profile's token estimate per request, or None if unknown
        """
        server_checker: ServerChecker = self._output_parts.get("server_checker")
        resource_reporter: ResourceReporter = self._output_parts.get("resource_reporter")
        aggregates: Dict[str, Any] = RunOutputWriter._build_aggregates(stage_summaries)
        verdict: str = "FAILED"
        if exit_code == 0:
            verdict = "PASSED"
        mode: str = "flat"
        if self._run_settings.get("ramp"):
            mode = "ramp"
        config: Dict[str, Any] = self._config_section(mode, estimated_tokens_per_request)
        raw_data: Dict[str, Any] = {
            "test_metadata": {
                "timestamp": strftime("%Y-%m-%dT%H:%M:%S%z"),
                "hostname": gethostname(),
                "python_version": python_version(),
                "platform": platform(),
                "neuro_san_version": server_checker.resolve_ns_version(),
                "neuro_san_studio_version": ServerChecker.get_package_version("neuro_san_studio"),
                "verdict": verdict,
                "exit_code": exit_code,
            },
            "config": config,
            "aggregates": aggregates,
            "stage_summaries": stage_summaries,
            "resource_rows": resource_reporter.get_resource_snapshots(),
            "client_resource_rows": resource_reporter.get_client_snapshots(),
        }
        json_metadata: Dict[str, Any] = JsonMetadata.build()
        raw_data.update(json_metadata)
        json_path: str = join(self._output_dir, LoadTestConstants.RAW_RESULTS_FILE_NAME)
        with open(json_path, "w", encoding="utf-8") as json_file:
            dump(raw_data, json_file, indent=2, default=str)

    def _config_section(self, mode: str, estimated_tokens_per_request: Optional[int]) -> Dict[str, Any]:
        """
        Build the "config" section of raw_results.json: the run settings, in CONFIG_KEYS order.

        :param mode: "flat", or "ramp" with --ramp
        :param estimated_tokens_per_request: The agent profile's token estimate per request, or None if unknown
        :return: The config section
        """
        hocon_files: List[str] = self._output_parts.get("hocon_files")
        profile_source: str = self.profile_source()
        other_values: Dict[str, Any] = {
            "mode": mode,
            "profile_source": profile_source,
            "hocon_files": hocon_files,
            "estimated_tokens_per_request": estimated_tokens_per_request,
        }
        config: Dict[str, Any] = {}
        key: str
        # Take each key from the values above when it is one of them, else from the run settings.
        for key in RunOutputWriter.CONFIG_KEYS:
            if key in other_values:
                config[key] = other_values.get(key)
            else:
                settings_key: str = RunOutputWriter.CONFIG_SETTINGS_KEYS.get(key, key)
                config[key] = self._run_settings.get(settings_key)
        return config

    def maybe_write_summary(self, stage_summaries: List[Dict[str, Any]],
                            server_chat_timing: List[Dict[str, object]]) -> None:
        """
        Write summary.txt for adv level only.

        With --no-dry-run: auto-write.  Otherwise prompt the user.

        :param stage_summaries: One summary dict per stage
        :param server_chat_timing: Server streaming_chat Start/Finish pairs for the test
        """
        if self._run_settings.get("level") != LoadTestConstants.LEVEL_ADV:
            return
        if not self._run_settings.get("no_dry_run"):
            if not self.confirm.ask("\nSave summary.txt?"):
                return
        writer: SummaryFileWriter = SummaryFileWriter(stage_summaries, self._run_settings,
                                                      server_chat_timing=server_chat_timing)
        writer.write(self._output_dir)

    def rename_interrupted(self) -> None:
        """
        Append _interrupted to the output directory name.
        """
        if self._output_dir is None:
            return
        new_path: str = self._output_dir + "_interrupted"
        try:
            rename(self._output_dir, new_path)
            self._output_dir = new_path
            self.logger.info("  Renamed output to: %s", new_path)
        except OSError as exc:
            # Caught-exception text goes through a SensitiveLogger; when LEAF_LOG_SENSITIVE is off, the plain
            # logger still names both folders.
            sensitive_logger: SensitiveLogger = SensitiveLogger(self.logger)
            if sensitive_logger.should_log():
                sensitive_logger.warning("  Could not rename output dir %s to %s: %s", self._output_dir, new_path, exc)
            else:
                self.logger.warning("  Could not rename output dir %s to %s", self._output_dir, new_path)

    def finalize_test_log(self, stage_summaries: List[Dict[str, Any]], history_recorder: HistoryRecorder) -> None:
        """
        Report the output directory and close the log handler.

        :param stage_summaries: One summary dict per stage
        :param history_recorder: History recorder that lists the history files
        """
        if self._output_dir is None:
            self._run_log.close()
            return
        has_failures: bool = False
        summary: Dict[str, Any]
        # Look for a stage with failed, timed-out or killed requests
        for summary in stage_summaries:
            counts: Dict[str, int] = summary.get("counts", {})
            if (counts.get(LoadTestConstants.STATUS_FAILED, 0) > 0
                    or counts.get(LoadTestConstants.STATUS_TIMEOUT, 0) > 0
                    or counts.get(LoadTestConstants.STATUS_KILLED, 0) > 0):
                has_failures = True
                break
        label: str = "OUTPUT FILES"
        if has_failures:
            label = "OUTPUT FILES (with failures)"
        self.logger.info("\n%s", Formatters.section_header(label))
        self.logger.info("  Directory:   %s", self._output_dir)
        json_path: str = join(self._output_dir, LoadTestConstants.RAW_RESULTS_FILE_NAME)
        if isfile(json_path):
            self.logger.info("  Raw results: %s", json_path)
        requests_dir: str = join(self._output_dir, LoadTestConstants.REQUESTS_DIR_NAME)
        if isdir(requests_dir):
            self.logger.info("  Requests:    %s", requests_dir)
        stdout_log_path: Optional[str] = self._run_log.get_path()
        if stdout_log_path is not None:
            self.logger.info("  Stdout log:  %s", stdout_log_path)
        history_recorder.log_existing_history_files()
        # Close the run log last so OUTPUT FILES is captured
        self._run_log.close()

    @staticmethod
    def collect_stage_results(stage_summaries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Collect the request results of every stage into one list.

        :param stage_summaries: The summary dict of each stage, each with a "results" list
        :return: The results of all stages, in stage order
        """
        all_results: List[Dict[str, Any]] = []
        summary: Dict[str, Any]
        # Collect the results of every stage.
        for summary in stage_summaries:
            stage_results: List[Dict[str, Any]] = summary.get("results", [])
            all_results.extend(stage_results)
        return all_results

    @staticmethod
    def _build_aggregates(stage_summaries: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Add up the request counts, time, latency, tokens and cost of the whole test.

        :param stage_summaries: One summary dict per stage
        :return: The "aggregates" dict of raw_results.json, with the following keys:
            "total_requests"         Number of requests
            "passed"                 Number of passed requests
            "failed"                 Number of failed requests
            "total_elapsed_seconds"  Time of all requests in seconds
            "avg_latency_seconds"    Average request time in seconds
            "total_tokens"           Total tokens
            "total_cost_usd"         Total cost in USD
        """
        all_results: List[Dict[str, Any]] = RunOutputWriter.collect_stage_results(stage_summaries)
        request_totals: Dict[str, Any] = RunOutputWriter._add_up_requests(all_results)
        stage_elapsed: List[float] = []
        summary: Dict[str, Any]
        # Collect the elapsed time of every stage.
        for summary in stage_summaries:
            summary_elapsed_seconds: float = summary.get("elapsed", 0)
            stage_elapsed.append(summary_elapsed_seconds)
        total_elapsed: float = sum(stage_elapsed)
        total_requests: int = request_totals.get("total_requests")
        passed: int = request_totals.get("passed")
        avg_latency_seconds: float = request_totals.get("avg_latency_seconds")
        total_cost_usd: float = request_totals.get("total_cost_usd")
        aggregates: Dict[str, Any] = {
            "total_requests": total_requests,
            "passed": passed,
            "failed": total_requests - passed,
            "total_elapsed_seconds": round(total_elapsed, 2),
            "avg_latency_seconds": round(avg_latency_seconds, 2),
            "total_tokens": request_totals.get("total_tokens"),
            "total_cost_usd": round(total_cost_usd, 6),
        }
        return aggregates

    @staticmethod
    def _add_up_requests(all_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Add up the tokens, cost, latency and pass count of every request.

        :param all_results: The request results of every stage
        :return: A dict with the following keys:
            "total_requests"       Number of requests
            "passed"               Number of passed requests
            "total_tokens"         Total tokens
            "total_cost_usd"       Total cost in USD
            "avg_latency_seconds"  Average request time in seconds, 0 without requests
        """
        total_tokens: int = 0
        costs: List[float] = []
        latencies: List[float] = []
        passed: int = 0
        result: Dict[str, Any]
        # Collect the tokens, cost, latency and pass count of every request.
        for result in all_results:
            total_tokens += result.get("total_tokens", 0)
            cost_usd: float = result.get("cost_usd", 0.0)
            costs.append(cost_usd)
            elapsed_seconds: float = result.get("elapsed", 0)
            latencies.append(elapsed_seconds)
            if result.get("status") == LoadTestConstants.STATUS_CREATED:
                passed += 1
        # Float totals use sum(), which adds floats with compensation; a += loop can differ in the last digit.
        total_cost: float = sum(costs)
        total_requests: int = len(all_results)
        avg_latency: float = 0
        if total_requests:
            avg_latency = sum(latencies) / total_requests
        request_totals: Dict[str, Any] = {
            "total_requests": total_requests,
            "passed": passed,
            "total_tokens": total_tokens,
            "total_cost_usd": total_cost,
            "avg_latency_seconds": avg_latency,
        }
        return request_totals
