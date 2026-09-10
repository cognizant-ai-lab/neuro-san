
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
import json
import os
import tempfile
from unittest import TestCase

from tests.load_tests.monitoring.server_log_monitor import ServerLogMonitor

# The server logs one record per line using the format in
# neuro_san/deploy/logging.hocon, with the reporting payload rendered by
# json.dumps(..., indent=4).  The indentation makes each record span
# several physical lines, and the record's own request_id arrives on the
# closing line -- which is why blocks are collected across lines rather
# than parsed one line at a time.
LOG_RECORD_FORMAT = (
    '{{"message": "{message}", "user_id": "None", '
    '"Timestamp": "2026-07-26T19:00:00", "source": "server", '
    '"message_type": "metrics", "request_id": "{request_id}"}}\n'
)


class TestParseTokenAccountingSince(TestCase):
    """
    Unit tests for ServerLogMonitor.parse_token_accounting_since().

    Token, cost, and LLM-call figures come from these blocks whenever
    the client cannot supply them (notably under --minimal), so the
    parser is pinned against the server's real log shape: if the
    server's format drifts, these fail instead of silently reporting
    zero tokens.
    """

    def setUp(self):
        """Create a scratch log file removed again after each test."""
        handle, self._log_path = tempfile.mkstemp(suffix=".log")
        os.close(handle)
        self.addCleanup(os.unlink, self._log_path)

    @staticmethod
    def _reporting_record(request_id, *, total=1500, model="gpt-4o") -> str:
        """Render one 'Request reporting' record as the server writes it.

        Prompt and completion tokens are split 4:1 out of ``total`` so
        the three counts stay consistent with one another.
        """
        prompt = total * 4 // 5
        payload = {
            "total_cost": 0.0075,
            "total_tokens": total,
            "prompt_tokens": prompt,
            "completion_tokens": total - prompt,
            "successful_requests": 2,
            "time_taken_in_seconds": 12.5,
            "caller_model": model,
        }
        message = "Request reporting: " + json.dumps(payload, indent=4)
        return LOG_RECORD_FORMAT.format(
            message=message, request_id=request_id,
        )

    def _write(self, text) -> None:
        """Write the given log text to the scratch log file."""
        with open(self._log_path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def test_fields_are_extracted_from_a_multiline_record(self):
        """One record yields its token counts, call count, and model."""
        self._write(self._reporting_record("req-1"))
        monitor = ServerLogMonitor(self._log_path)

        entries = monitor.parse_token_accounting_since(0)

        self.assertEqual(list(entries), ["req-1"])
        self.assertEqual(entries["req-1"]["total_tokens"], 1500)
        self.assertEqual(entries["req-1"]["prompt_tokens"], 1200)
        self.assertEqual(entries["req-1"]["completion_tokens"], 300)
        self.assertEqual(entries["req-1"]["llm_calls"], 2)
        self.assertEqual(entries["req-1"]["model"], "gpt-4o")

    def test_each_request_is_keyed_separately(self):
        """Concurrent requests must not overwrite one another."""
        self._write(
            self._reporting_record("req-1", total=1500)
            + self._reporting_record("req-2", total=2500)
        )
        monitor = ServerLogMonitor(self._log_path)

        entries = monitor.parse_token_accounting_since(0)

        self.assertEqual(entries["req-1"]["total_tokens"], 1500)
        self.assertEqual(entries["req-2"]["total_tokens"], 2500)

    def test_reporting_agent_comes_from_the_following_done_line(self):
        """The network name is taken from the Done-with line after it."""
        self._write(
            self._reporting_record("req-1")
            + LOG_RECORD_FORMAT.format(
                message="Done with music_nerd_pro.StreamingChat",
                request_id="req-1",
            )
        )
        monitor = ServerLogMonitor(self._log_path)

        entries = monitor.parse_token_accounting_since(0)

        self.assertEqual(
            entries["req-1"]["reporting_agent"], "music_nerd_pro",
        )

    def test_only_records_after_the_position_are_parsed(self):
        """Reading from a saved offset ignores earlier runs' records."""
        first = self._reporting_record("req-old")
        self._write(first + self._reporting_record("req-new"))
        monitor = ServerLogMonitor(self._log_path)

        entries = monitor.parse_token_accounting_since(len(first))

        self.assertEqual(list(entries), ["req-new"])

    def test_unrelated_log_traffic_is_ignored(self):
        """Ordinary log lines produce no entries."""
        self._write(
            LOG_RECORD_FORMAT.format(
                message="Starting agent server", request_id="None",
            )
        )
        monitor = ServerLogMonitor(self._log_path)

        self.assertEqual(monitor.parse_token_accounting_since(0), {})

    def test_no_server_log_yields_nothing(self):
        """Runs without --server-log get an empty result, not an error."""
        monitor = ServerLogMonitor(None)

        self.assertEqual(monitor.parse_token_accounting_since(0), {})

    def test_no_position_yields_nothing(self):
        """A missing start offset yields an empty result, not an error."""
        self._write(self._reporting_record("req-1"))
        monitor = ServerLogMonitor(self._log_path)

        self.assertEqual(monitor.parse_token_accounting_since(None), {})
