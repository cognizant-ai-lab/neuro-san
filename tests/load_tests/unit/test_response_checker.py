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

from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from unittest import TestCase

from neuro_san.message.processors.basic_message_processor import BasicMessageProcessor

from tests.load_tests.load_test_constants import LoadTestConstants
from tests.load_tests.prompts.agent_profile import AgentProfile
from tests.load_tests.traffic.response_checker import ResponseChecker


class TestResponseChecker(TestCase):
    """
    Unit tests for ResponseChecker: check_response() hands the hocon response block to
    DataDrivenTestsDriver.test_response_keys and turns the captured assertion failures
    into a failure reason; failure_patterns go through the same path as text.not_keywords.
    """

    def test_no_checks_passes(self) -> None:
        """
        An empty response block and no failure_patterns never fail.
        """
        checker: ResponseChecker = TestResponseChecker._checker()
        processor: BasicMessageProcessor = TestResponseChecker._processor("hi")
        reason: Optional[str] = checker.check_response(processor, {})
        self.assertIsNone(reason)

    def test_not_value_requires_present_non_empty_sly_data(self) -> None:
        """
        sly_data.<key>: { not_value: "" } fails on a missing or empty key.
        """
        checks: Dict[str, Any] = {"sly_data": {"agent_reservations": {"not_value": ""}}}
        checker: ResponseChecker = TestResponseChecker._checker()
        reservations: List[Dict[str, Any]] = [{"reservation_id": "r-1"}]
        with_reservations: BasicMessageProcessor = TestResponseChecker._processor(
            "ok", {"agent_reservations": reservations})
        without_reservations: BasicMessageProcessor = TestResponseChecker._processor(
            "ok", {"agent_network_name": "n"})
        empty_reservations: BasicMessageProcessor = TestResponseChecker._processor(
            "ok", {"agent_reservations": ""})
        with_reason: Optional[str] = checker.check_response(with_reservations, checks)
        without_reason: Optional[str] = checker.check_response(without_reservations, checks)
        empty_reason: Optional[str] = checker.check_response(empty_reservations, checks)
        self.assertIsNone(with_reason)
        self.assertIn("agent_reservations", without_reason)
        self.assertIn("agent_reservations", empty_reason)

    def test_keywords_check_on_answer_text(self) -> None:
        """
        text: { keywords: [...] } is applied to the answer.
        """
        checks: Dict[str, Any] = {"text": {"keywords": ["Bonjour"]}}
        checker: ResponseChecker = TestResponseChecker._checker()
        bonjour_processor: BasicMessageProcessor = TestResponseChecker._processor("Bonjour!")
        hello_processor: BasicMessageProcessor = TestResponseChecker._processor("Hello!")
        bonjour_reason: Optional[str] = checker.check_response(bonjour_processor, checks)
        hello_reason: Optional[str] = checker.check_response(hello_processor, checks)
        self.assertIsNone(bonjour_reason)
        self.assertIsNotNone(hello_reason)

    def test_failure_patterns_fail_the_request(self) -> None:
        """
        failure_patterns are checked as text.not_keywords.
        """
        checker: ResponseChecker = TestResponseChecker._checker(["No fully-specified LLM found"])
        fine_processor: BasicMessageProcessor = TestResponseChecker._processor("fine")
        fine_reason: Optional[str] = checker.check_response(fine_processor, {})
        self.assertIsNone(fine_reason)
        error_processor: BasicMessageProcessor = TestResponseChecker._processor(
            "Error: No fully-specified LLM found")
        reason: Optional[str] = checker.check_response(error_processor, {})
        self.assertIn("No fully-specified LLM found", reason)

    def test_all_failures_are_reported(self) -> None:
        """
        Every failed check appears in the reason, not just the first.
        """
        sly_data_checks: Dict[str, Any] = {
            "a": {"not_value": ""},
            "b": {"not_value": ""},
        }
        checks: Dict[str, Any] = {"sly_data": sly_data_checks}
        checker: ResponseChecker = TestResponseChecker._checker()
        processor: BasicMessageProcessor = TestResponseChecker._processor("ok", {})
        reason: Optional[str] = checker.check_response(processor, checks)
        self.assertIn("sly_data.a", reason)
        self.assertIn("sly_data.b", reason)

    def test_long_failure_line_is_shortened(self) -> None:
        """
        A failure line longer than the limit is cut and ends with "...".
        """
        long_line: str = ""
        # Grow the line one character at a time until it passes the limit.
        while len(long_line) <= LoadTestConstants.FAILURE_REASON_LINE_LIMIT:
            long_line += "x"
        long_message: str = "\n" + long_line + "\nsecond line"
        first_line: str = ResponseChecker.first_line(long_message)
        first_line_length: int = len(first_line)
        ends_with_dots: bool = first_line.endswith("...")
        self.assertEqual(LoadTestConstants.FAILURE_REASON_LINE_LIMIT, first_line_length)
        self.assertTrue(ends_with_dots)

    @staticmethod
    def _processor(answer: str, sly_data: Optional[Dict[str, Any]] = None) -> BasicMessageProcessor:
        """
        Return a BasicMessageProcessor that has seen an AI answer, then the
        final AGENT_FRAMEWORK message that carries chat_context and sly_data
        (the shape a streaming_chat stream ends with).

        :param answer: Text of the AI message
        :param sly_data: sly_data of the final AGENT_FRAMEWORK message, or None to send no such message
        :return: The processor
        """
        processor: BasicMessageProcessor = BasicMessageProcessor()
        ai_message: Dict[str, Any] = {
            "type": "AI",
            "text": answer,
        }
        processor.process_message(ai_message)
        if sly_data is not None:
            framework_message: Dict[str, Any] = {
                "type": "AGENT_FRAMEWORK",
                "chat_context": {},
                "sly_data": sly_data,
            }
            processor.process_message(framework_message)
        return processor

    @staticmethod
    def _checker(failure_patterns: Optional[List[str]] = None) -> ResponseChecker:
        """
        Return a checker over a one-prompt profile.

        :param failure_patterns: failure_patterns of the profile, or None for none
        :return: The checker
        """
        patterns: List[str] = []
        if failure_patterns is not None:
            patterns = failure_patterns
        profile_settings: Dict[str, Any] = {
            "prompts": ["p"],
            "failure_patterns": patterns,
        }
        profile: AgentProfile = AgentProfile("x", profile_settings)
        return ResponseChecker(profile)
