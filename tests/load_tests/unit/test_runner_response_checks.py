
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
"""Unit tests for TrafficRunner response checks via the data-driven evaluators."""

from argparse import Namespace
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from unittest import TestCase

from neuro_san.message.processors.basic_message_processor import BasicMessageProcessor
from tests.load_tests.prompts.agent_profile import AgentProfile
from tests.load_tests.traffic.runner import TrafficRunner


class TestRunnerResponseChecks(TestCase):
    """
    TrafficRunner.check_response hands the hocon response block to
    DataDrivenTestsDriver.test_response_keys and turns the captured
    assertion failures into a failure reason; failure_patterns go
    through the same path as text.not_keywords.
    """

    @staticmethod
    def _processor(answer: str, sly_data: Optional[Dict[str, Any]] = None) -> BasicMessageProcessor:
        """Return a BasicMessageProcessor that has seen an AI answer, then the
        final AGENT_FRAMEWORK message that carries chat_context and sly_data
        (the shape a streaming_chat stream ends with)."""
        processor = BasicMessageProcessor()
        processor.process_message({"type": "AI", "text": answer})
        if sly_data is not None:
            processor.process_message({
                "type": "AGENT_FRAMEWORK", "chat_context": {}, "sly_data": sly_data,
            })
        return processor

    @staticmethod
    def _runner(failure_patterns: Optional[List[str]] = None) -> TrafficRunner:
        """Return a runner over a one-prompt profile."""
        profile = AgentProfile("x", {"prompts": ["p"], "failure_patterns": failure_patterns or []})
        return TrafficRunner(Namespace(same_prompt=False), profile)

    def test_no_checks_passes(self) -> None:
        """An empty response block and no failure_patterns never fail."""
        reason = self._runner().check_response(self._processor("hi"), {})
        self.assertIsNone(reason)

    def test_not_value_requires_present_non_empty_sly_data(self) -> None:
        """sly_data.<key>: { not_value: "" } fails on a missing or empty key."""
        checks = {"sly_data": {"agent_reservations": {"not_value": ""}}}
        runner = self._runner()
        self.assertIsNone(runner.check_response(
            self._processor("ok", {"agent_reservations": [{"reservation_id": "r-1"}]}), checks,
        ))
        self.assertIn("agent_reservations", runner.check_response(
            self._processor("ok", {"agent_network_name": "n"}), checks,
        ))
        self.assertIn("agent_reservations", runner.check_response(
            self._processor("ok", {"agent_reservations": ""}), checks,
        ))

    def test_keywords_check_on_answer_text(self) -> None:
        """text: { keywords: [...] } is applied to the answer."""
        checks = {"text": {"keywords": ["Bonjour"]}}
        runner = self._runner()
        self.assertIsNone(runner.check_response(self._processor("Bonjour!"), checks))
        self.assertIsNotNone(runner.check_response(self._processor("Hello!"), checks))

    def test_failure_patterns_fail_the_request(self) -> None:
        """failure_patterns are checked as text.not_keywords."""
        runner = self._runner(["No fully-specified LLM found"])
        self.assertIsNone(runner.check_response(self._processor("fine"), {}))
        reason = runner.check_response(self._processor("Error: No fully-specified LLM found"), {})
        self.assertIn("No fully-specified LLM found", reason)

    def test_all_failures_are_reported(self) -> None:
        """Every failed check appears in the reason, not just the first."""
        checks = {"sly_data": {"a": {"not_value": ""}, "b": {"not_value": ""}}}
        reason = self._runner().check_response(self._processor("ok", {}), checks)
        self.assertIn("sly_data.a", reason)
        self.assertIn("sly_data.b", reason)
