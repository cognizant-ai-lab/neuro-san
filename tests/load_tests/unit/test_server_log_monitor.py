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
import tempfile
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
    The ServerLogMonitor readers of retry, cancel and validation lines, fed log lines in the exact format their
    writers make: each writer's own message and args, rendered by the "structured" formatter of
    neuro_san/deploy/logging.hocon.
    """

    @override
    def setUp(self) -> None:
        """
        Create a scratch server log file removed again after each test, and the server's log formatter.
        """
        file_descriptor: int = 0
        self._log_path: str = ""
        file_descriptor, self._log_path = tempfile.mkstemp(suffix=".log")
        os.close(file_descriptor)
        self.addCleanup(os.unlink, self._log_path)
        logging_hocon: str = os.path.join(os.path.dirname(neuro_san.__file__), "deploy", "logging.hocon")
        logging_config: Dict[str, Any] = EasyHoconPersistence().restore(file_reference=logging_hocon)
        structured_format: str = logging_config.get("formatters").get("structured").get("format")
        self._formatter: logging.Formatter = logging.Formatter(structured_format)

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
        record: logging.LogRecord = logging.makeLogRecord({
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
