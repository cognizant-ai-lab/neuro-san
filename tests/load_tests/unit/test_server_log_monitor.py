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

from json import dumps
from logging import Formatter
from logging import LogRecord
from logging import makeLogRecord
from os import close
from os import unlink
from os.path import dirname
from os.path import join
from tempfile import mkstemp
from typing import Any
from typing import Dict
from typing import List
from unittest import TestCase

from leaf_common.persistence.easy.easy_hocon_persistence import EasyHoconPersistence
from typing_extensions import override

import neuro_san
from tests.load_tests.monitoring.server_log_monitor import ServerLogMonitor


class TestServerLogMonitor(TestCase):
    """
    The ServerLogMonitor readers of retry, cancel, validation and token-accounting lines, fed log lines in the
    exact format their writers make: each writer's own message and args, rendered by the "structured" formatter of
    neuro_san/deploy/logging.hocon.

    The parse_token_accounting_since() tests pin the reader of "Request reporting" blocks against the server's
    real log shape. Token, cost, and LLM-call figures come from these blocks whenever the client cannot supply
    them (notably under --minimal): if the server's format drifts, these fail instead of silently reporting
    zero tokens.
    """

    # The server logs one record per line using the format in
    # neuro_san/deploy/logging.hocon, with the reporting payload rendered by
    # json.dumps(..., indent=4).  The indentation makes each record span
    # several physical lines, and the record's own request_id arrives on the
    # closing line -- which is why blocks are collected across lines rather
    # than parsed one line at a time.
    LOG_RECORD_FORMAT: str = (
        '{{"message": "{message}", "user_id": "None", '
        '"Timestamp": "2026-07-26T19:00:00", "source": "server", '
        '"message_type": "metrics", "request_id": "{request_id}"}}\n'
    )

    @override
    def setUp(self) -> None:
        """
        Create a scratch server log file removed again after each test, and the server's log formatter.
        """
        file_descriptor: int = 0
        self._log_path: str = ""
        file_descriptor, self._log_path = mkstemp(suffix=".log")
        close(file_descriptor)
        self.addCleanup(unlink, self._log_path)
        logging_hocon: str = join(dirname(neuro_san.__file__), "deploy", "logging.hocon")
        logging_config: Dict[str, Any] = EasyHoconPersistence().restore(file_reference=logging_hocon)
        structured_format: str = logging_config.get("formatters").get("structured").get("format")
        self._formatter: Formatter = Formatter(structured_format)

    def test_retries_are_counted_by_the_error_type_in_parentheses(self) -> None:
        """
        RunContextRunnable.journal_retry_reason() lines are counted under their error type, next to the
        retries the LLM provider SDK makes itself.
        """
        value_error: ValueError = ValueError("Invalid json output")
        key_error: KeyError = KeyError("choices")
        self._write([
            self._render("request-3", f"Retrying: the model's output could not be parsed "
                                      f"({value_error.__class__.__name__}) - {value_error}"),
            self._render("request-3", f"Retrying: the response was missing an expected field "
                                      f"({key_error.__class__.__name__}) - {key_error}"),
            self._render("request-4", f"Retrying: the model's output could not be parsed "
                                      f"({value_error.__class__.__name__}) - {value_error}"),
            self._render("request-4", "Retrying request to /chat/completions in 0.45 seconds"),
        ])
        retry_counts: Dict[str, int] = ServerLogMonitor(self._log_path).count_retries_since(0)
        self.assertEqual(retry_counts, {
            "ValueError": 2,
            "KeyError": 1,
            "ProviderRetry": 1,
        })

    def test_cancelled_task_gets_the_agent_of_its_own_request(self) -> None:
        """
        The AsyncioExecutor cancel line names the request id of the cancelled task, so the disconnection gets the
        agent from that request's Start line, even when another request logged in between.
        """
        self._write([
            self._render("request-3", "[%d] Start %s", 1, "hello_world/streaming_chat"),
            self._render("request-3", "Request handler stream closed."),
            self._render("request-4", "[%d] Start %s", 2, "music_nerd/streaming_chat"),
            self._render("None", "Task from %s was cancelled", "request-3:DataDrivenChatSession.streaming_chat"),
        ])
        disconnections: List[Dict[str, str]] = ServerLogMonitor(self._log_path).scan_disconnections_since(0)
        self.assertEqual(disconnections, [{
            "request_id": "request-3",
            "agent": "hello_world",
        }])

    def test_validation_errors_are_read_from_the_python_list(self) -> None:
        """
        Every error of the "Validation errors: %s" list is kept, whether Python wrote it in single quotes or, when
        it holds a single quote, in double quotes.
        """
        validation_errors: List[str] = ["Agent 'frontman' has no tools", "Missing instructions", "Unknown agent: x"]
        self._write([
            self._render("request-3", "Validating toolbox agents..."),
            self._render("request-3", "Validation errors: %s", validation_errors),
            self._render("request-3", "Invoking agent network designer to fix the issues (attempt %d/%d).", 1, 3),
        ])
        events: List[Dict[str, Any]] = ServerLogMonitor(self._log_path).parse_validation_events_since(0)
        self.assertEqual(events, [{
            "request_id": "request-3",
            "attempts": 1,
            "fix_cycles": 1,
            "errors": validation_errors,
        }])

    def _render(self, request_id: str, message: str, *log_args: Any) -> str:
        """
        Render one server log line the way the server's "structured" formatter writes it.

        :param request_id: The request id that LogContextFilter puts on the line
        :param message: The writer's log message, with % placeholders
        :param log_args: The writer's arguments for those placeholders, as passed to logger.info()
        :return: One formatted log line
        """
        record: LogRecord = makeLogRecord({
            "msg": message,
            "args": log_args,
            "levelname": "INFO",
            "user_id": "None",
            "iso_timestamp": "2026-10-20T09:00:00",
            "source": "neuro-san",
            "message_type": "Other",
            "request_id": request_id,
        })
        return self._formatter.format(record)

    def _write(self, lines: List[str]) -> None:
        """
        Write the log lines to the scratch server log.

        :param lines: The formatted log lines
        """
        with open(self._log_path, "w", encoding="utf-8") as log_file:
            log_file.write("\n".join(lines) + "\n")

    @staticmethod
    def _reporting_record(request_id: str, total_tokens: int = 1500, model: str = "gpt-4o") -> str:
        """
        Render one 'Request reporting' record as the server writes it.

        Prompt and completion tokens are split 4:1 out of ``total_tokens`` so
        the three counts stay consistent with one another.

        :param request_id: Request id in the log record
        :param total_tokens: Total tokens
        :param model: caller_model value
        :return: One formatted log record
        """
        # 80% of the tokens, rounded down, e.g. 1001 -> 800.
        prompt: int = int(total_tokens * 4 / 5)
        completion: int = total_tokens - prompt
        payload: Dict[str, Any] = {
            "total_cost": 0.0075,
            "total_tokens": total_tokens,
            "prompt_tokens": prompt,
            "completion_tokens": completion,
            "successful_requests": 2,
            "time_taken_in_seconds": 12.5,
            "caller_model": model,
        }
        payload_text: str = dumps(payload, indent=4)
        message: str = "Request reporting: " + payload_text
        return TestServerLogMonitor.LOG_RECORD_FORMAT.format(message=message, request_id=request_id)

    def _write_text(self, text: str) -> None:
        """
        Write the given log text to the scratch log file.

        :param text: Log text to write
        """
        with open(self._log_path, "w", encoding="utf-8") as file_handle:
            file_handle.write(text)

    def test_fields_are_extracted_from_a_multiline_record(self) -> None:
        """
        One record yields its token counts, call count, and model.
        """
        record_text: str = TestServerLogMonitor._reporting_record("req-1")
        self._write_text(record_text)
        monitor: ServerLogMonitor = ServerLogMonitor(self._log_path)

        entries: Dict[str, Dict[str, Any]] = monitor.parse_token_accounting_since(0)

        request_ids: List[str] = list(entries.keys())
        self.assertEqual(request_ids, ["req-1"])
        entry: Dict[str, Any] = entries.get("req-1", {})
        total_tokens: int = entry.get("total_tokens", 0)
        prompt_tokens: int = entry.get("prompt_tokens", 0)
        completion_tokens: int = entry.get("completion_tokens", 0)
        llm_calls: int = entry.get("llm_calls", 0)
        model: str = entry.get("model", "")
        self.assertEqual(total_tokens, 1500)
        self.assertEqual(prompt_tokens, 1200)
        self.assertEqual(completion_tokens, 300)
        self.assertEqual(llm_calls, 2)
        self.assertEqual(model, "gpt-4o")

    def test_each_request_is_keyed_separately(self) -> None:
        """
        Concurrent requests must not overwrite one another.
        """
        first_record: str = TestServerLogMonitor._reporting_record("req-1", total_tokens=1500)
        second_record: str = TestServerLogMonitor._reporting_record("req-2", total_tokens=2500)
        self._write_text(first_record + second_record)
        monitor: ServerLogMonitor = ServerLogMonitor(self._log_path)

        entries: Dict[str, Dict[str, Any]] = monitor.parse_token_accounting_since(0)

        first_entry: Dict[str, Any] = entries.get("req-1", {})
        second_entry: Dict[str, Any] = entries.get("req-2", {})
        first_total_tokens: int = first_entry.get("total_tokens", 0)
        second_total_tokens: int = second_entry.get("total_tokens", 0)
        self.assertEqual(first_total_tokens, 1500)
        self.assertEqual(second_total_tokens, 2500)

    def test_reporting_agent_comes_from_the_following_done_line(self) -> None:
        """
        The network name is taken from the Done-with line after it.
        """
        record_text: str = TestServerLogMonitor._reporting_record("req-1")
        done_text: str = TestServerLogMonitor.LOG_RECORD_FORMAT.format(
            message="Done with music_nerd_pro.StreamingChat",
            request_id="req-1",
        )
        self._write_text(record_text + done_text)
        monitor: ServerLogMonitor = ServerLogMonitor(self._log_path)

        entries: Dict[str, Dict[str, Any]] = monitor.parse_token_accounting_since(0)

        entry: Dict[str, Any] = entries.get("req-1", {})
        reporting_agent: str = entry.get("reporting_agent", "")
        self.assertEqual(reporting_agent, "music_nerd_pro")

    def test_only_records_after_the_position_are_parsed(self) -> None:
        """
        Reading from a saved offset ignores earlier runs' records.
        """
        first: str = TestServerLogMonitor._reporting_record("req-old")
        second: str = TestServerLogMonitor._reporting_record("req-new")
        self._write_text(first + second)
        monitor: ServerLogMonitor = ServerLogMonitor(self._log_path)
        position: int = len(first)

        entries: Dict[str, Dict[str, Any]] = monitor.parse_token_accounting_since(position)

        request_ids: List[str] = list(entries.keys())
        self.assertEqual(request_ids, ["req-new"])

    def test_unrelated_log_traffic_is_ignored(self) -> None:
        """
        Ordinary log lines produce no entries.
        """
        log_text: str = TestServerLogMonitor.LOG_RECORD_FORMAT.format(message="Starting agent server",
                                                                      request_id="None")
        self._write_text(log_text)
        monitor: ServerLogMonitor = ServerLogMonitor(self._log_path)

        entries: Dict[str, Dict[str, Any]] = monitor.parse_token_accounting_since(0)

        self.assertEqual(entries, {})

    def test_no_server_log_yields_nothing(self) -> None:
        """
        Runs without --server-log get an empty result, not an error.
        """
        monitor: ServerLogMonitor = ServerLogMonitor(None)

        entries: Dict[str, Dict[str, Any]] = monitor.parse_token_accounting_since(0)

        self.assertEqual(entries, {})

    def test_no_position_yields_nothing(self) -> None:
        """
        A missing start offset yields an empty result, not an error.
        """
        record_text: str = TestServerLogMonitor._reporting_record("req-1")
        self._write_text(record_text)
        monitor: ServerLogMonitor = ServerLogMonitor(self._log_path)

        entries: Dict[str, Dict[str, Any]] = monitor.parse_token_accounting_since(None)

        self.assertEqual(entries, {})
