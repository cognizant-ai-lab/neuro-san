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

"""Post-run result counting and server-side request verification.

Counts results by status (CREATED, FAILED, TIMEOUT, KILLED), logs
per-stage summaries, retry activity from the server log, server-side
request validation (sent vs received), and client disconnections.
"""

import logging

from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from tests.load_tests.config import RETRY_ERROR_TYPES
from tests.load_tests.config import RETRY_LABELS
from tests.load_tests.config import STATUS_CREATED
from tests.load_tests.config import STATUS_FAILED
from tests.load_tests.config import STATUS_KILLED
from tests.load_tests.config import STATUS_TIMEOUT
from tests.load_tests.reporting.formatters import Formatters

logger: logging.Logger = logging.getLogger(__name__)


class OutputValidator:
    """Counts results and logs server-side request verification."""

    @staticmethod
    def count_results(results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Count results by status type.

        :param results: Request results of the stage
        :return: Count per status; unknown statuses count as failed
        """
        counts: Dict[str, Any] = {STATUS_CREATED: 0, STATUS_FAILED: 0, STATUS_TIMEOUT: 0, STATUS_KILLED: 0}
        for result in results:
            status: str = result.get("status", STATUS_FAILED)
            if status not in counts:
                status = STATUS_FAILED
            counts[status] = counts.get(status, 0) + 1
        return counts

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    @staticmethod
    def log_stage_results(actual_requests: int, counts: Dict[str, Any], elapsed_seconds: float, timeout: float,
                          idle_timeout: float, show_counts: bool = True) -> None:
        """Log per-stage summary of request results.

        When ``show_counts`` is False (single-stage runs, where the
        counts are repeated verbatim in OVERALL RESULTS), only the
        Duration/Avg line is printed to avoid duplication.

        :param actual_requests: Requests sent in the stage
        :param counts: Count per status from count_results
        :param elapsed_seconds: Stage wall time in seconds
        :param timeout: --request-timeout in seconds, shown in the timed-out line
        :param idle_timeout: --idle-timeout in seconds, shown in the killed line
        :param show_counts: False to log only the Duration/Avg line
        """
        if show_counts:
            logger.info("\n  Requests: %s", actual_requests)
            logger.info("    Created: %s  (success criteria met)", counts.get(STATUS_CREATED, 0))
            logger.info("    Failed:  %s  (error or crash)", counts.get(STATUS_FAILED, 0))
            logger.info("    Timed out: %s  (hit %ss hard cap)", counts.get(STATUS_TIMEOUT, 0), timeout)
            logger.info(
                "    Killed:  %s  (no output for %ss, presumed hanging)",
                counts.get(STATUS_KILLED, 0), idle_timeout,
            )
        average_seconds_per_request: float = (
            elapsed_seconds / actual_requests
            if actual_requests else 0
        )
        logger.info(
            "  Duration: %s | Avg: %s per request",
            Formatters.fmt_duration(elapsed_seconds, precision=2),
            Formatters.fmt_duration(average_seconds_per_request, precision=2),
        )

    @staticmethod
    def log_retry_activity(retries: Dict[str, int], total_retries: int, actual_requests: int) -> None:
        """
        Log retry activity from server log.

        :param retries: Retry count per error type, from the server log
        :param total_retries: Retries of every type
        :param actual_requests: Requests sent in the stage, used for the amplification
        """
        logger.info("\n  Retry activity (from server log):")
        for error_type in RETRY_ERROR_TYPES:
            count: int = retries.get(error_type, 0)
            label: str = RETRY_LABELS.get(error_type, f"{error_type} retries")
            logger.info("    %s: %s", label, count)
        logger.info("    Total retries:  %s", total_retries)
        amplification: float = Formatters.compute_amplification(actual_requests, total_retries)
        logger.info(
            "    Amplification:  %.2fx (%s total LLM attempts for %s requests)",
            amplification,
            actual_requests + total_retries,
            actual_requests,
        )

    @staticmethod
    def log_server_validation(server_counts: Dict[str, Any], actual_requests: int, agent_name: str) -> None:
        """Log server-side request validation from log counts.

        Compares the number of requests the server received (from the
        server log) against the number the client sent, flagging only
        the case of too few: the log belongs to the server, not to this
        run, so another client testing the same agent inflates the
        count.  Extra starts are therefore not treated as a mismatch,
        while missing ones always are.

        :param server_counts: Start and finish counts from the server log; logs nothing if primary_started is None
        :param actual_requests: Requests the client sent
        :param agent_name: Agent name shown in the lines
        """
        if server_counts.get("primary_started") is None:
            return
        primary_started: int = server_counts.get("primary_started")
        primary_finished: int = server_counts.get("primary_finished")
        total_started: int = server_counts.get("total_started")
        total_finished: int = server_counts.get("total_finished")
        internal_calls: int = total_started - primary_started
        match_label: str = (
            "OK" if primary_started >= actual_requests else "MISMATCH"
        )
        logger.info("\n  Server-side validation (from server log):")
        logger.info("    %s received:  %s/%s  (%s)", agent_name, primary_started, actual_requests, match_label)
        logger.info("    %s completed: %s/%s", agent_name, primary_finished, actual_requests)
        if internal_calls > 0:
            logger.info("    Internal calls: %s additional streaming_chat calls (recursive)", internal_calls)
        logger.info("    Total server calls: %s started, %s finished", total_started, total_finished)
        if primary_started < actual_requests:
            logger.warning(
                "    WARNING: Server received %s %s requests but %s were sent",
                primary_started, agent_name, actual_requests,
            )

    @staticmethod
    def log_disconnections(disconnections: List[Dict[str, str]]) -> None:
        """
        Log client disconnections detected in the current stage.

        :param disconnections: Disconnection events with agent, request_id and client_request
        """
        if not disconnections:
            return
        logger.warning("\n  Client disconnections detected: %s", len(disconnections))
        for disconnection in disconnections:
            agent: str = disconnection.get("agent", "unknown")
            request_id: str = disconnection.get("request_id", "unknown")
            client_request: Optional[str] = disconnection.get("client_request")
            label: str = (
                f"{client_request}/{request_id}" if client_request
                else request_id
            )
            logger.warning("    %s: %s still running at disconnect", label, agent)

    @staticmethod
    def log_server_errors(server_errors: List[Dict[str, str]]) -> None:
        """
        Log server-side "Errors detected:" events for the stage.

        :param server_errors: Error events with request_id and message
        """
        if not server_errors:
            return
        logger.warning("\n  Server errors detected: %s", len(server_errors))
        for server_error in server_errors:
            request_id: str = server_error.get("request_id", "unknown")
            message: str = server_error.get("message", "")
            logger.warning("    %s: %s", request_id, message)

    @staticmethod
    def log_tool_warnings(tool_warnings: List[Dict[str, str]]) -> None:
        """Log server-side tool-creation warnings for the stage.

        These mean a requested tool was unavailable to an agent; they
        don't affect the created network, but a high count under load
        may indicate tool-creation failures worth investigating.

        :param tool_warnings: Tool warning events with request_id and message
        """
        if not tool_warnings:
            return
        logger.warning("\n  Tool-creation warnings: %s", len(tool_warnings))
        for tool_warning in tool_warnings:
            request_id: str = tool_warning.get("request_id", "unknown")
            message: str = tool_warning.get("message", "")
            logger.warning("    %s: %s", request_id, message)

    @staticmethod
    def check_permission_failures(results: List[Dict[str, Any]], agent_name: str) -> bool:
        """Check if all requests failed with a permissions error.

        When neuro-san-studio organizes agents under subdirectories
        (e.g. registries/basic/hello_world), the --agent value must
        include the subdirectory prefix (basic/hello_world).

        Returns True if the test should abort (all requests failed
        with a permissions-related error).

        :param results: Request results of the stage
        :param agent_name: --agent value, used in the error message
        :return: True if every request failed with a permissions error
        """
        if not results:
            return False
        all_failed: bool = all(
            result.get("status") == STATUS_FAILED for result in results
        )
        if not all_failed:
            return False
        permission_keywords: List[str] = ["permissions", "permission", "not found"]
        has_permission_error: bool = any(
            any(
                keyword in (result.get("error") or "").lower()
                for keyword in permission_keywords
            )
            for result in results
        )
        if not has_permission_error:
            return False
        if "/" in agent_name:
            logger.error(
                "\n  ERROR: All requests failed with a permissions error for agent '%s'.\n"
                "  Verify that the agent is registered in the server's AGENT_REGISTRY_PATH and that your user\n"
                "  has the correct permissions for the network.\n\n"
                "  Aborting test.",
                agent_name,
            )
        else:
            logger.error(
                "\n  ERROR: All requests failed with a permissions error.\n"
                "  The --agent value '%s' may need a registry subdirectory prefix.\n"
                "  For example, if the agent is registered under\n"
                "  registries/basic/, use:\n"
                "    --agent basic/%s\n\n"
                "  Aborting test.",
                agent_name, agent_name,
            )
        return True

    @staticmethod
    def check_timeout_abort(counts: Dict[str, Any]) -> bool:
        """Check if any requests hit a timeout or were killed.

        Returns True if the test should abort because at least one
        request exceeded its idle-timeout, request-timeout, or was
        killed by stage-timeout.

        :param counts: Count per status from count_results
        :return: True if any request timed out or was killed
        """
        timed_out: int = counts.get(STATUS_TIMEOUT, 0)
        killed: int = counts.get(STATUS_KILLED, 0)
        timed_out_or_killed: int = timed_out + killed
        if timed_out_or_killed == 0:
            return False
        abort_reasons: List[str] = []
        if timed_out:
            abort_reasons.append(f"{timed_out} timed out")
        if killed:
            abort_reasons.append(f"{killed} killed by stage-timeout")
        logger.warning(
            "\n  ABORT: %s — %s.\n"
            "  Stopping test and reporting available results.",
            ", ".join(abort_reasons), f"{timed_out_or_killed} request(s) failed",
        )
        return True
