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

from logging import Logger
from logging import getLogger
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from leaf_common.parsers.dictionary_extractor import DictionaryExtractor

from neuro_san.message.processors.basic_message_processor import BasicMessageProcessor
from neuro_san.test.driver.assert_capture import AssertCapture
from neuro_san.test.driver.data_driven_tests_driver import DataDrivenTestsDriver

from tests.load_tests.load_test_constants import LoadTestConstants
from tests.load_tests.prompts.agent_profile import AgentProfile
from tests.load_tests.traffic.load_test_assert_forwarder import LoadTestAssertForwarder


class ResponseChecker:
    """
    Checks one completed request against its hocon response checks and the profile's failure patterns.

    Gives TrafficRunner a one-line failure reason, or None when every check passes.
    """

    def __init__(self, profile: AgentProfile) -> None:
        """
        Constructor.

        :param profile: Prompts and response checks for the agent under test, for its failure patterns
        """
        self.logger: Logger = getLogger(self.__class__.__name__)
        self._profile: AgentProfile = profile

    def check_response(self, processor: Optional[BasicMessageProcessor],
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

        :param processor: The BasicMessageProcessor that saw the whole response stream, or None when there is none
        :param response_checks: The hocon ``response`` block for this request's prompt
        :return: A one-line reason when any check failed, else None
        """
        forwarder: LoadTestAssertForwarder = LoadTestAssertForwarder()
        asserts: AssertCapture = AssertCapture(forwarder)
        driver: DataDrivenTestsDriver = DataDrivenTestsDriver(asserts)
        blocks: List[Dict[str, Any]] = self._response_check_blocks(response_checks)
        reasons: List[str] = []
        block: Dict[str, Any]
        # Run the checks of each block: the prompt's checks, then the failure patterns.
        for block in blocks:
            extractor: DictionaryExtractor = DictionaryExtractor(block)
            key: str
            # One test_response_keys call per top-level test key
            # (text, sly_data.<field>, ...) so each failure can be
            # labelled with the key it belongs to; the evaluators'
            # own messages only show the compared values.
            for key in ResponseChecker._top_level_keys(block):
                earlier_failures: List[AssertionError] = asserts.get_asserts()
                seen: int = len(earlier_failures)
                driver.test_response_keys(processor, extractor, [key], asserts, [])
                key_reasons: List[str] = ResponseChecker._new_failure_reasons(key, asserts, seen)
                reasons.extend(key_reasons)
        if not reasons:
            return None
        reason_text: str = "; ".join(reasons)
        return reason_text

    def _response_check_blocks(self, response_checks: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        List the check blocks of one request: the prompt's checks, then the failure patterns as text.not_keywords.

        :param response_checks: The hocon ``response`` block for this request's prompt
        :return: The blocks to check, in that order
        """
        blocks: List[Dict[str, Any]] = [response_checks]
        failure_patterns: List[str] = self._profile.get_failure_patterns()
        if failure_patterns:
            failure_block: Dict[str, Any] = {"text": {"not_keywords": failure_patterns}}
            blocks.append(failure_block)
        return blocks

    @staticmethod
    def _top_level_keys(block: Dict[str, Any]) -> List[str]:
        """
        Return the test keys of a response block.

        :param block: A hocon ``response`` block
        :return: text and structure when present, plus sly_data.<field>
                 for each field under sly_data
        """
        keys: List[str] = []
        test_key: str
        # Keep each test key the block has, with one key per sly_data field.
        for test_key in DataDrivenTestsDriver.TEST_KEYS:
            # A test key holds a dict, a list or a plain value, depending on the evaluator.
            checks: Any = block.get(test_key)
            if checks is None:
                continue
            if test_key == "sly_data" and isinstance(checks, dict):
                sly_data_checks: Dict[str, Any] = checks
                field: str
                # One sly_data.<field> key per field.
                for field in sly_data_checks.keys():
                    keys.append(f"{test_key}.{field}")
            else:
                keys.append(test_key)
        return keys

    @staticmethod
    def _new_failure_reasons(key: str, asserts: AssertCapture, seen: int) -> List[str]:
        """
        Label each failure that the checks of one key added to the AssertCapture.

        :param key: The top-level test key whose checks just ran
        :param asserts: The AssertCapture that collects the failed assertions
        :param seen: How many failures the AssertCapture held before the checks of this key ran
        :return: One "<key>: <first line of the failure>" reason per new failure
        """
        reasons: List[str] = []
        all_failures: List[AssertionError] = asserts.get_asserts()
        new_failures: List[AssertionError] = all_failures[seen:]
        failure: AssertionError
        # One reason per new failure, labelled with its key.
        for failure in new_failures:
            failure_text: str = str(failure)
            first_line: str = ResponseChecker.first_line(failure_text)
            reasons.append(f"{key}: {first_line}")
        return reasons

    @staticmethod
    def first_line(message: str) -> str:
        """
        Return the first non-empty line of an assertion message, shortened.

        :param message: The AssertionError text, possibly multi-line
        :return: Its first non-empty line, cut to LoadTestConstants.FAILURE_REASON_LINE_LIMIT
        """
        line: str = message
        part: str
        # Find the first line that is not blank.
        for part in message.splitlines():
            if part.strip():
                line = part
                break
        line = line.strip()
        if len(line) <= LoadTestConstants.FAILURE_REASON_LINE_LIMIT:
            return line
        kept_length: int = LoadTestConstants.FAILURE_REASON_LINE_LIMIT - 3
        kept_text: str = line[:kept_length]
        return kept_text + "..."
