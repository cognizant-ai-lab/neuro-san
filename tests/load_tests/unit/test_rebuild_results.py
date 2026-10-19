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
from logging import Logger
from tempfile import TemporaryDirectory
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
from tests.load_tests.config import DEFAULT_FIXTURES_HOCON_DIR
from tests.load_tests.config import LEGACY_RUN_LOG_FILE_NAME
from tests.load_tests.config import LEVEL_MIN
from tests.load_tests.config import RAW_RESULTS_FILE_NAME
from tests.load_tests.config import STATUS_CREATED
from tests.load_tests.config import STATUS_FAILED
from tests.load_tests.config import STATUS_KILLED
from tests.load_tests.config import STATUS_TIMEOUT
from tests.load_tests.config import STDOUT_LOG_FILE_NAME
from tests.load_tests.load_test_arguments import LoadTestArguments
from tests.load_tests.load_test_cli import LoadTestOrchestrator
from tests.load_tests.reporting.rebuild_results import ResultsRebuilder
from tests.load_tests.traffic.agent_request_result import AgentRequestResult


class TestResultsRebuilder(TestCase):
    """
    A real client-only load-test run writes stdout.log, progress.log and requests/. With raw_results.json deleted,
    ResultsRebuilder rebuilds the same agent, statuses and per-request durations from those files.
    Only the agent call and the server port check are patched.
    """

    AGENT: str = "hello_world"
    REQUEST_COUNT: int = 5
    ANSWER_SECONDS: float = 0.1
    # The run log prints durations with 2 decimals.
    DURATION_TOLERANCE_SECONDS: float = 0.01
    FIXTURES_HOCON_DIR: str = TOP_LEVEL_DIR.get_file_in_basis(os.path.join("..", DEFAULT_FIXTURES_HOCON_DIR))

    @override
    def setUp(self) -> None:
        """
        Let INFO lines reach the run log, as they do when load_test_cli runs from the command line.
        """
        root_logger: Logger = logging.getLogger()
        self.addCleanup(root_logger.setLevel, root_logger.level)
        root_logger.setLevel(logging.INFO)

    def test_json_profile_run_rebuilds_five_passed(self) -> None:
        """
        A JSON-profile run with 5 passed requests rebuilds as 5 passed, 0 failed.
        """
        original: Dict[str, Any] = {}
        rebuilt: Dict[str, Any] = {}
        original, rebuilt = self._run_and_rebuild([], {}, STDOUT_LOG_FILE_NAME)
        self._assert_same_run(original, rebuilt, TestResultsRebuilder.REQUEST_COUNT, 0)

    def test_hocon_fixture_run_rebuilds_five_passed(self) -> None:
        """
        A HOCON-fixture run with 5 passed requests rebuilds as 5 passed, 0 failed.
        """
        extra_args: List[str] = ["--fixtures-hocon-dir", TestResultsRebuilder.FIXTURES_HOCON_DIR]
        original: Dict[str, Any] = {}
        rebuilt: Dict[str, Any] = {}
        original, rebuilt = self._run_and_rebuild(extra_args, {}, STDOUT_LOG_FILE_NAME)
        self._assert_same_run(original, rebuilt, TestResultsRebuilder.REQUEST_COUNT, 0)

    def test_legacy_run_log_name_still_rebuilds(self) -> None:
        """
        The same run log saved under the legacy name load_test.log rebuilds the same way.
        """
        original: Dict[str, Any] = {}
        rebuilt: Dict[str, Any] = {}
        original, rebuilt = self._run_and_rebuild([], {}, LEGACY_RUN_LOG_FILE_NAME)
        self._assert_same_run(original, rebuilt, TestResultsRebuilder.REQUEST_COUNT, 0)

    def test_failed_timeout_and_killed_stay_distinct(self) -> None:
        """
        FAILED, TIMEOUT and KILLED requests keep their own status and duration after a rebuild.
        """
        statuses: Dict[str, str] = {
            "What can you help me with?": STATUS_TIMEOUT,
            "Tell me something interesting about yourself": STATUS_KILLED,
            "What is the meaning of hello world in programming?": STATUS_FAILED,
        }
        # --allow-caching sends the profile prompts without a suffix, so each one picks its status.
        extra_args: List[str] = ["--allow-caching"]
        original: Dict[str, Any] = {}
        rebuilt: Dict[str, Any] = {}
        original, rebuilt = self._run_and_rebuild(extra_args, statuses, STDOUT_LOG_FILE_NAME)
        self._assert_same_run(original, rebuilt, 2, 3)
        rebuilt_statuses: List[str] = []
        result: Dict[str, Any]
        # Collect every rebuilt status to check that no failure kind is merged into another.
        for result in self._requests_by_id(rebuilt).values():
            rebuilt_statuses.append(result.get("status"))
        rebuilt_statuses.sort()
        expected_statuses: List[str] = [STATUS_CREATED, STATUS_CREATED, STATUS_FAILED, STATUS_KILLED, STATUS_TIMEOUT]
        self.assertEqual(expected_statuses, rebuilt_statuses)

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
            "--level", LEVEL_MIN, "--no-dry-run", "--settle-time", "0",
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
                LoadTestOrchestrator(args).run()
            run_dir: str = self._run_dir(output_base)
            raw_results_path: str = os.path.join(run_dir, RAW_RESULTS_FILE_NAME)
            raw_results_file = EasyJsonPersistence(full_ref=raw_results_path, must_exist=True)
            original = raw_results_file.restore()
            os.remove(raw_results_path)
            if run_log_name != STDOUT_LOG_FILE_NAME:
                stdout_log_path: str = os.path.join(run_dir, STDOUT_LOG_FILE_NAME)
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
        status: str = statuses.get(prompt, STATUS_CREATED)
        return AgentRequestResult(status, processor, "Hello there", TestResultsRebuilder.ANSWER_SECONDS, {})

    def _run_dir(self, output_base: str) -> str:
        """
        Find the one run directory the load test wrote.

        :param output_base: The --output-dir of the run
        :return: Path of the run directory
        """
        level_dir: str = os.path.join(output_base, LEVEL_MIN)
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
