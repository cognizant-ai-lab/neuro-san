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

import logging
import os
import time
from argparse import Namespace
from functools import partial
from json import dumps
from logging import Logger
from shutil import rmtree
from tempfile import TemporaryDirectory
from tempfile import mkdtemp
from typing import Any
from typing import Dict
from typing import List
from typing import Tuple
from unittest import TestCase
from unittest.mock import patch

from leaf_common.parsers.dictionary_extractor import DictionaryExtractor
from leaf_common.persistence.easy.easy_json_persistence import EasyJsonPersistence
from typing_extensions import override

from neuro_san import TOP_LEVEL_DIR
from neuro_san.message.processors.basic_message_processor import BasicMessageProcessor
from tests.load_tests.load_test_constants import LoadTestConstants
from tests.load_tests.load_test_arguments import LoadTestArguments
from tests.load_tests.load_test_cli import LoadTestCli
from tests.load_tests.reporting.results_rebuilder import ResultsRebuilder
from tests.load_tests.traffic.agent_request_result import AgentRequestResult


# These tests call deliberately-internal helpers directly; suppress
# protected-access warnings file-wide.
# pylint: disable=protected-access
class TestResultsRebuilder(TestCase):
    """
    Unit tests for ResultsRebuilder: the agent, statuses, per-request durations and aggregates it rebuilds.

    A real client-only load-test run writes stdout.log, progress.log and requests/. With raw_results.json deleted,
    ResultsRebuilder rebuilds the same agent, statuses and per-request durations from those files.
    Only the agent call and the server port check are patched.

    A rebuilt run is often the only surviving record of an interrupted run, so its headline numbers have to mean
    what they say, and a request must come back with the status the run actually reported. A timed-out or killed
    request usually printed a reservation_id before the client gave up, so partial output must not be read as
    evidence that the request succeeded.
    """

    AGENT: str = "hello_world"
    REQUEST_COUNT: int = 5
    ANSWER_SECONDS: float = 0.1
    # The run log prints durations with 2 decimals.
    DURATION_TOLERANCE_SECONDS: float = 0.01
    FIXTURES_HOCON_DIR: str = TOP_LEVEL_DIR.get_file_in_basis(
        os.path.join("..", LoadTestConstants.DEFAULT_FIXTURES_HOCON_DIR))

    @override
    def setUp(self) -> None:
        """
        Let INFO lines reach the run log, as they do when load_test_cli runs from the command line,
        and create a run directory with a requests/ folder, removed again after each test.
        """
        root_logger: Logger = logging.getLogger()
        self.addCleanup(root_logger.setLevel, root_logger.level)
        root_logger.setLevel(logging.INFO)
        self._scratch_run_dir: str = mkdtemp()
        self.addCleanup(rmtree, self._scratch_run_dir)
        os.makedirs(os.path.join(self._scratch_run_dir, LoadTestConstants.REQUESTS_DIR_NAME))

    def test_json_profile_run_rebuilds_five_passed(self) -> None:
        """
        A JSON-profile run with 5 passed requests rebuilds as 5 passed, 0 failed.
        """
        original: Dict[str, Any] = {}
        rebuilt: Dict[str, Any] = {}
        original, rebuilt = self._run_and_rebuild([], {}, LoadTestConstants.STDOUT_LOG_FILE_NAME)
        self._assert_same_run(original, rebuilt, TestResultsRebuilder.REQUEST_COUNT, 0)

    def test_hocon_fixture_run_rebuilds_five_passed(self) -> None:
        """
        A HOCON-fixture run with 5 passed requests rebuilds as 5 passed, 0 failed.
        """
        extra_args: List[str] = ["--fixtures-hocon-dir", TestResultsRebuilder.FIXTURES_HOCON_DIR]
        original: Dict[str, Any] = {}
        rebuilt: Dict[str, Any] = {}
        original, rebuilt = self._run_and_rebuild(extra_args, {}, LoadTestConstants.STDOUT_LOG_FILE_NAME)
        self._assert_same_run(original, rebuilt, TestResultsRebuilder.REQUEST_COUNT, 0)

    def test_legacy_run_log_name_still_rebuilds(self) -> None:
        """
        The same run log saved under the legacy name load_test.log rebuilds the same way.
        """
        original: Dict[str, Any] = {}
        rebuilt: Dict[str, Any] = {}
        original, rebuilt = self._run_and_rebuild([], {}, LoadTestConstants.LEGACY_RUN_LOG_FILE_NAME)
        self._assert_same_run(original, rebuilt, TestResultsRebuilder.REQUEST_COUNT, 0)

    def test_failed_timeout_and_killed_stay_distinct(self) -> None:
        """
        FAILED, TIMEOUT and KILLED requests keep their own status and duration after a rebuild.
        """
        statuses: Dict[str, str] = {
            "What can you help me with?": LoadTestConstants.STATUS_TIMEOUT,
            "Tell me something interesting about yourself": LoadTestConstants.STATUS_KILLED,
            "What is the meaning of hello world in programming?": LoadTestConstants.STATUS_FAILED,
        }
        # --allow-caching sends the profile prompts without a suffix, so each one picks its status.
        extra_args: List[str] = ["--allow-caching"]
        original: Dict[str, Any] = {}
        rebuilt: Dict[str, Any] = {}
        original, rebuilt = self._run_and_rebuild(extra_args, statuses, LoadTestConstants.STDOUT_LOG_FILE_NAME)
        self._assert_same_run(original, rebuilt, 2, 3)
        rebuilt_statuses: List[str] = []
        result: Dict[str, Any]
        # Collect every rebuilt status to check that no failure kind is merged into another.
        for result in self._requests_by_id(rebuilt).values():
            rebuilt_statuses.append(result.get("status"))
        rebuilt_statuses.sort()
        expected_statuses: List[str] = [
            LoadTestConstants.STATUS_CREATED,
            LoadTestConstants.STATUS_CREATED,
            LoadTestConstants.STATUS_FAILED,
            LoadTestConstants.STATUS_KILLED,
            LoadTestConstants.STATUS_TIMEOUT,
        ]
        self.assertEqual(expected_statuses, rebuilt_statuses)

    def test_average_latency_is_the_mean_request_time(self) -> None:
        """
        Latency averages the requests, not the run.

        Requests overlap, so dividing the slowest request by the
        request count would shrink the average by the concurrency
        factor and make a slow run look fast.
        """
        aggregates: Dict[str, Any] = self._build_run({1: 30.0, 2: 30.0, 3: 30.0})

        self.assertEqual(aggregates.get("avg_latency_seconds", 0.0), 30.0)

    def test_average_latency_reflects_uneven_requests(self) -> None:
        """
        The mean is taken over every request's own elapsed time.
        """
        aggregates: Dict[str, Any] = self._build_run({1: 1.0, 2: 2.0, 3: 6.0})

        self.assertEqual(aggregates.get("avg_latency_seconds", 0.0), 3.0)

    def test_total_elapsed_is_the_slowest_request(self) -> None:
        """
        Total elapsed still stands in for the run's wall clock.
        """
        aggregates: Dict[str, Any] = self._build_run({1: 1.0, 2: 2.0, 3: 6.0})

        self.assertEqual(aggregates.get("total_elapsed_seconds", 0.0), 6.0)

    def test_partial_output_does_not_promote_a_timeout(self) -> None:
        """
        A TIMEOUT with a reservation_id stays a TIMEOUT.
        """
        self._write_request(1)
        self._write_log("Request 1: TIMEOUT (61.00s (1m))\n")

        result: Dict[str, Any] = self._rebuild().get("request-1", {})
        self.assertEqual(result.get("status", ""), LoadTestConstants.STATUS_TIMEOUT)

    def test_partial_output_does_not_promote_a_kill(self) -> None:
        """
        A KILLED request with a reservation_id stays KILLED.
        """
        self._write_request(1)
        self._write_log("Request 1: KILLED (5.00s)\n")

        result: Dict[str, Any] = self._rebuild().get("request-1", {})
        self.assertEqual(result.get("status", ""), LoadTestConstants.STATUS_KILLED)

    def test_partial_output_alone_is_not_success(self) -> None:
        """
        With no log line, partial output is not counted as passing.
        """
        self._write_request(1)
        self._write_log("")

        result: Dict[str, Any] = self._rebuild().get("request-1", {})
        self.assertEqual(result.get("status", ""), LoadTestConstants.STATUS_FAILED)

    def test_successful_request_is_still_rebuilt_as_created(self) -> None:
        """
        The normal case is unaffected.
        """
        self._write_request(1)
        self._write_log("Request 1: CREATED (3.00s)\n")

        result: Dict[str, Any] = self._rebuild().get("request-1", {})

        self.assertEqual(result.get("status", ""), LoadTestConstants.STATUS_CREATED)
        self.assertEqual(result.get("elapsed", 0.0), 3.0)

    def test_each_reported_status_is_preserved(self) -> None:
        """
        CREATED, FAILED, TIMEOUT and KILLED all survive a rebuild.
        """
        status: str
        # Each reported status comes back unchanged.
        for status in [LoadTestConstants.STATUS_CREATED, LoadTestConstants.STATUS_FAILED,
                       LoadTestConstants.STATUS_TIMEOUT, LoadTestConstants.STATUS_KILLED]:
            with self.subTest(status=status):
                self.assertEqual(ResultsRebuilder._resolve_status({"status": status}), status)

    def test_missing_log_line_counts_as_failed(self) -> None:
        """
        A request never seen to finish is a failure, not a success.

        Failures past LoadTestConstants.FAILURE_LOG_LIMIT are never printed, so an absent
        log line is the normal case for a heavily failing run.
        """
        self.assertEqual(ResultsRebuilder._resolve_status({}), LoadTestConstants.STATUS_FAILED)

    def test_unrecognized_status_counts_as_failed(self) -> None:
        """
        An unknown status word is never promoted to success.
        """
        self.assertEqual(ResultsRebuilder._resolve_status({"status": "WEIRD"}), LoadTestConstants.STATUS_FAILED)

    def _run_and_rebuild(self, extra_args: List[str], statuses: Dict[str, str],
                         run_log_name: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Run a 5-request client-only load test, delete raw_results.json, then rebuild it.

        :param extra_args: Command-line arguments added to the base run arguments
        :param statuses: Prompt to the status its request returns; other prompts return CREATED
        :param run_log_name: Name the run log has when the rebuild reads it: stdout.log or the legacy load_test.log
        :return: (raw_results.json the run wrote, raw_results.json the rebuild wrote)
        """
        argv: List[str] = [
            "load_test_cli", "--agent", TestResultsRebuilder.AGENT,
            "--num-requests", str(TestResultsRebuilder.REQUEST_COUNT), "--client-only",
            "--level", LoadTestConstants.LEVEL_MIN, "--no-dry-run", "--settle-time", "0",
        ]
        argv.extend(extra_args)
        answer: partial = partial(self._answer, statuses)
        original: Dict[str, Any] = {}
        rebuilt: Dict[str, Any] = {}
        with TemporaryDirectory() as output_base:
            argv.extend(["--output-dir", output_base])
            args: Namespace = Namespace()
            with patch("sys.argv", argv):
                args = LoadTestArguments.parse_args("")
            with patch("tests.load_tests.traffic.agent_request_executor.AgentRequestExecutor.execute_request",
                       side_effect=answer), \
                    patch("tests.load_tests.validation.environment_validator.EnvironmentValidator.is_port_open",
                          return_value=True):
                LoadTestCli(args).run()
            run_dir: str = self._run_dir(output_base)
            raw_results_path: str = os.path.join(run_dir, LoadTestConstants.RAW_RESULTS_FILE_NAME)
            raw_results_file = EasyJsonPersistence(full_ref=raw_results_path, must_exist=True)
            original = raw_results_file.restore()
            os.remove(raw_results_path)
            if run_log_name != LoadTestConstants.STDOUT_LOG_FILE_NAME:
                stdout_log_path: str = os.path.join(run_dir, LoadTestConstants.STDOUT_LOG_FILE_NAME)
                renamed_log_path: str = os.path.join(run_dir, run_log_name)
                os.rename(stdout_log_path, renamed_log_path)
            ResultsRebuilder(run_dir).run()
            rebuilt = raw_results_file.restore()
        return original, rebuilt

    # Same parameters as AgentRequestExecutor.execute_request, which this method stands in for.
    # pylint: disable=too-many-arguments,too-many-positional-arguments,unused-argument
    @staticmethod
    def _answer(statuses: Dict[str, str], host: str, port: int, agent: str, prompt: str, timeout_seconds: float,
                idle_timeout_seconds: float, use_https: bool = False,
                chat_filter_type: str = "MAXIMAL") -> AgentRequestResult:
        """
        Stand in for AgentRequestExecutor.execute_request: wait a little, then answer.

        :param statuses: Prompt to the status its request returns; other prompts return CREATED
        :param host: Server host name, unused
        :param port: Server port, unused
        :param agent: Agent name, unused
        :param prompt: The request's prompt
        :param timeout_seconds: Request timeout, unused
        :param idle_timeout_seconds: Idle timeout, unused
        :param use_https: True for HTTPS, unused
        :param chat_filter_type: Chat filter, unused
        :return: The request result
        """
        time.sleep(TestResultsRebuilder.ANSWER_SECONDS)
        processor: BasicMessageProcessor = BasicMessageProcessor()
        processor.process_message({"type": "AI", "text": "Hello there"})
        status: str = statuses.get(prompt, LoadTestConstants.STATUS_CREATED)
        return AgentRequestResult(status, processor, "Hello there", TestResultsRebuilder.ANSWER_SECONDS, {})

    def _run_dir(self, output_base: str) -> str:
        """
        Find the one run directory the load test wrote.

        :param output_base: The --output-dir of the run
        :return: Path of the run directory
        """
        level_dir: str = os.path.join(output_base, LoadTestConstants.LEVEL_MIN)
        entries: List[str] = os.listdir(level_dir)
        self.assertEqual(1, len(entries))
        return os.path.join(level_dir, entries[0])

    @staticmethod
    def _requests_by_id(raw_results: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        """
        Index the per-request results of a raw_results.json by request id.

        :param raw_results: Parsed raw_results.json
        :return: Request id to its result
        """
        keyed: Dict[str, Dict[str, Any]] = {}
        stage: Dict[str, Any]
        # Each stage holds the results of its own requests.
        for stage in raw_results.get("stage_summaries", []):
            result: Dict[str, Any]
            # Key each request result by its id.
            for result in stage.get("results", []):
                keyed[result.get("request_id")] = result
        return keyed

    def _assert_same_run(self, original: Dict[str, Any], rebuilt: Dict[str, Any], passed: int, failed: int) -> None:
        """
        Check the rebuild has the run's agent, counts, and each request's status and duration.

        :param original: raw_results.json the run wrote
        :param rebuilt: raw_results.json the rebuild wrote
        :param passed: Expected passed count, in both files
        :param failed: Expected failed count, in both files
        """
        original_extractor = DictionaryExtractor(original)
        rebuilt_extractor = DictionaryExtractor(rebuilt)
        self.assertEqual(TestResultsRebuilder.AGENT, rebuilt_extractor.get("config.agent"))
        self.assertEqual(TestResultsRebuilder.REQUEST_COUNT, rebuilt_extractor.get("config.num_requests"))
        self.assertEqual(passed, original_extractor.get("aggregates.passed"))
        self.assertEqual(failed, original_extractor.get("aggregates.failed"))
        self.assertEqual(passed, rebuilt_extractor.get("aggregates.passed"))
        self.assertEqual(failed, rebuilt_extractor.get("aggregates.failed"))
        original_requests: Dict[str, Dict[str, Any]] = self._requests_by_id(original)
        rebuilt_requests: Dict[str, Dict[str, Any]] = self._requests_by_id(rebuilt)
        original_request_ids: List[str] = sorted(original_requests.keys())
        rebuilt_request_ids: List[str] = sorted(rebuilt_requests.keys())
        self.assertEqual(original_request_ids, rebuilt_request_ids)
        shortest_seconds: float = TestResultsRebuilder.ANSWER_SECONDS - TestResultsRebuilder.DURATION_TOLERANCE_SECONDS
        request_id: str
        result: Dict[str, Any]
        # Each rebuilt request keeps its status and its duration, to the precision of the run log.
        for request_id, result in original_requests.items():
            rebuilt_result: Dict[str, Any] = rebuilt_requests.get(request_id, {})
            self.assertEqual(result.get("status"), rebuilt_result.get("status"), request_id)
            self.assertAlmostEqual(result.get("elapsed"), rebuilt_result.get("elapsed"),
                                   delta=TestResultsRebuilder.DURATION_TOLERANCE_SECONDS, msg=request_id)
            self.assertGreaterEqual(rebuilt_result.get("elapsed"), shortest_seconds, request_id)

    def _build_run(self, elapsed_seconds_by_id: Dict[int, float]) -> Dict[str, Any]:
        """
        Rebuild a run of successful requests with the given timings.

        :param elapsed_seconds_by_id: Elapsed seconds per request id
        :return: The "aggregates" dictionary read back from raw_results.json, with keys such as
            "avg_latency_seconds" and "total_elapsed_seconds"
        """
        log_text: str = ""
        request_id: int
        elapsed_seconds: float
        # Write the response file and the progress line of each request.
        for request_id, elapsed_seconds in elapsed_seconds_by_id.items():
            self._write_request(request_id)
            log_text += f"Request {request_id}: CREATED ({elapsed_seconds:.2f}s)\n"
        self._write_log(log_text)

        ResultsRebuilder(self._scratch_run_dir).run()

        json_path: str = os.path.join(self._scratch_run_dir, LoadTestConstants.RAW_RESULTS_FILE_NAME)
        raw_results_file = EasyJsonPersistence(full_ref=json_path, must_exist=True)
        raw_results: Dict[str, Any] = raw_results_file.restore()
        aggregates: Dict[str, Any] = raw_results.get("aggregates", {})
        return aggregates

    def _write_request(self, request_id: int) -> None:
        """
        Write stdout for a request that got as far as reserving.

        :param request_id: Request id used in the file name and reservation id
        """
        path: str = os.path.join(self._scratch_run_dir, LoadTestConstants.REQUESTS_DIR_NAME,
                                 f"request_{request_id}_stdout.txt")
        response: Dict[str, str] = {
            "reservation_id": f"abc-{request_id}",
            "agent_network_name": "music_nerd",
        }
        response_line: str = dumps(response)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(response_line + "\n")

    def _write_log(self, text: str) -> None:
        """
        Write the run log the rebuild reads timing from.

        :param text: Log text to write
        """
        path: str = os.path.join(self._scratch_run_dir, LoadTestConstants.LEGACY_RUN_LOG_FILE_NAME)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def _rebuild(self) -> Dict[str, Dict[str, Any]]:
        """
        Rebuild the run and return results keyed by request id.

        :return: A dictionary from each result's "request_id" (such as "request-1") to that request's result
        """
        rebuilder: ResultsRebuilder = ResultsRebuilder(self._scratch_run_dir)
        requests_dir: str = os.path.join(self._scratch_run_dir, LoadTestConstants.REQUESTS_DIR_NAME)
        timing: Dict[int, Dict[str, Any]] = rebuilder._parse_timing()
        results: List[Dict[str, Any]] = rebuilder._scan_requests(requests_dir, timing)
        results_by_request_id: Dict[str, Dict[str, Any]] = {}
        result: Dict[str, Any]
        # Key each result by its request id.
        for result in results:
            request_id: str = result.get("request_id")
            results_by_request_id[request_id] = result
        return results_by_request_id
