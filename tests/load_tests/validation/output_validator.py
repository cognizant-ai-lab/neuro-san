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

from typing import List

from tests.load_tests.config import Formatters
from tests.load_tests.config import RequestResult
from tests.load_tests.config import RETRY_ERROR_TYPES
from tests.load_tests.config import STATUS_CREATED
from tests.load_tests.config import STATUS_FAILED
from tests.load_tests.config import STATUS_KILLED
from tests.load_tests.config import STATUS_TIMEOUT
from tests.load_tests.config import StatusCounts

logger = logging.getLogger(__name__)


class OutputValidator:
    """Counts results and logs server-side request verification."""

    @staticmethod
    def count_results(results) -> StatusCounts:
        """Count results by status type."""
        counts: StatusCounts = {
            STATUS_CREATED: 0,
            STATUS_FAILED: 0,
            STATUS_TIMEOUT: 0,
            STATUS_KILLED: 0,
        }
        for result in results:
            status = result.get("status", STATUS_FAILED)
            if status not in counts:
                status = STATUS_FAILED
            counts[status] = counts.get(status, 0) + 1
        return counts

    # pylint: disable=too-many-arguments
    @staticmethod
    def log_stage_results(actual_requests, counts, elapsed, *,
                          timeout, idle_timeout,
                          skip_reservation_check=False,
                          show_counts=True) -> None:
        """Log per-stage summary of request results.

        When ``show_counts`` is False (single-stage runs, where the
        counts are repeated verbatim in OVERALL RESULTS), only the
        Duration/Avg line is printed to avoid duplication.
        """
        if show_counts:
            logger.info("\n  Requests: %s", actual_requests)
            if skip_reservation_check:
                confirm_label = "output fields confirmed"
            else:
                confirm_label = "success criteria met"
            logger.info(
                "    Created: %s  (%s)",
                counts.get(STATUS_CREATED, 0), confirm_label,
            )
            logger.info(
                "    Failed:  %s  (error or crash)",
                counts.get(STATUS_FAILED, 0),
            )
            logger.info(
                "    Timed out: %s  (hit %ss hard cap)",
                counts.get(STATUS_TIMEOUT, 0), timeout,
            )
            logger.info(
                "    Killed:  %s  (no output for %ss, presumed hanging)",
                counts.get(STATUS_KILLED, 0), idle_timeout,
            )
        avg_per = (
            elapsed / actual_requests
            if actual_requests else 0
        )
        logger.info(
            "  Duration: %s | Avg: %s per request",
            Formatters.fmt_duration(elapsed, precision=2),
            Formatters.fmt_duration(avg_per, precision=2),
        )

    @staticmethod
    def log_retry_activity(
            retries, total_retries, actual_requests,
    ) -> None:
        """Log retry activity from server log."""
        logger.info(
            "\n  max_attempts retry activity (from server log):",
        )
        for error_type in RETRY_ERROR_TYPES:
            count = retries.get(error_type, 0)
            logger.info("    %s retries: %s", error_type, count)
        logger.info("    Total retries:  %s", total_retries)
        amplification = Formatters.compute_amplification(
            actual_requests, total_retries,
        )
        logger.info(
            "    Amplification:  %.2fx "
            "(%s total LLM attempts for %s requests)",
            amplification,
            actual_requests + total_retries,
            actual_requests,
        )

    @staticmethod
    def log_server_validation(
            server_counts, actual_requests, agent_name,
    ) -> None:
        """Log server-side request validation from log counts.

        Compares the number of requests the server received (from the
        server log) against the number the client sent, flagging any
        mismatch.
        """
        if server_counts.get("primary_started") is None:
            return
        pri_started = server_counts.get("primary_started")
        pri_finished = server_counts.get("primary_finished")
        total_started = server_counts.get("total_started")
        total_finished = server_counts.get("total_finished")
        internal_calls = total_started - pri_started
        match_label = (
            "OK" if pri_started >= actual_requests else "MISMATCH"
        )
        logger.info(
            "\n  Server-side validation (from server log):",
        )
        logger.info(
            "    %s received:  %s/%s  (%s)",
            agent_name, pri_started, actual_requests, match_label,
        )
        logger.info(
            "    %s completed: %s/%s",
            agent_name, pri_finished, actual_requests,
        )
        if internal_calls > 0:
            logger.info(
                "    Internal calls: %s additional "
                "streaming_chat calls (recursive)",
                internal_calls,
            )
        logger.info(
            "    Total server calls: %s started, %s finished",
            total_started, total_finished,
        )
        if pri_started < actual_requests:
            logger.warning(
                "    WARNING: Server received %s %s requests "
                "but %s were sent",
                pri_started, agent_name, actual_requests,
            )

    @staticmethod
    def log_disconnections(disconnections) -> None:
        """Log client disconnections detected in the current stage."""
        if not disconnections:
            return
        logger.warning(
            "\n  Client disconnections detected: %s",
            len(disconnections),
        )
        for disc in disconnections:
            agent = disc.get("agent", "unknown")
            req_id = disc.get("request_id", "unknown")
            client_req = disc.get("client_request")
            label = (
                f"{client_req}/{req_id}" if client_req
                else req_id
            )
            logger.warning(
                "    %s: %s still running at disconnect",
                label, agent,
            )

    @staticmethod
    def log_server_errors(server_errors) -> None:
        """Log server-side "Errors detected:" events for the stage."""
        if not server_errors:
            return
        logger.warning(
            "\n  Server errors detected: %s",
            len(server_errors),
        )
        for err in server_errors:
            req_id = err.get("request_id", "unknown")
            message = err.get("message", "")
            logger.warning("    %s: %s", req_id, message)

    @staticmethod
    def check_permission_failures(
            results: List[RequestResult], agent_name: str,
    ) -> bool:
        """Check if all requests failed with a permissions error.

        When neuro-san-studio organizes agents under subdirectories
        (e.g. registries/basic/hello_world), the --agent value must
        include the subdirectory prefix (basic/hello_world).

        Returns True if the test should abort (all requests failed
        with a permissions-related error).
        """
        if not results:
            return False
        all_failed = all(
            r.get("status") == STATUS_FAILED for r in results
        )
        if not all_failed:
            return False
        permission_keywords = ["permissions", "permission", "not found"]
        has_perm_error = any(
            any(
                kw in (r.get("error") or "").lower()
                for kw in permission_keywords
            )
            for r in results
        )
        if not has_perm_error:
            return False
        if "/" in agent_name:
            logger.error(
                "\n  ERROR: All requests failed with a permissions "
                "error for agent '%s'.\n"
                "  Verify that the agent is registered in the "
                "server's AGENT_REGISTRY_PATH and that your user\n"
                "  has the correct permissions for the network.\n\n"
                "  Aborting test.",
                agent_name,
            )
        else:
            logger.error(
                "\n  ERROR: All requests failed with a permissions "
                "error.\n"
                "  The --agent value '%s' may need a registry "
                "subdirectory prefix.\n"
                "  For example, if the agent is registered under\n"
                "  registries/basic/, use:\n"
                "    --agent basic/%s\n\n"
                "  Aborting test.",
                agent_name, agent_name,
            )
        return True

    @staticmethod
    def check_timeout_abort(
            counts: "StatusCounts",
    ) -> bool:
        """Check if any requests hit a timeout or were killed.

        Returns True if the test should abort because at least one
        request exceeded its idle-timeout, request-timeout, or was
        killed by stage-timeout.
        """
        timed_out = counts.get(STATUS_TIMEOUT, 0)
        killed = counts.get(STATUS_KILLED, 0)
        total_bad = timed_out + killed
        if total_bad == 0:
            return False
        parts = []
        if timed_out:
            parts.append(
                f"{timed_out} timed out"
            )
        if killed:
            parts.append(
                f"{killed} killed by stage-timeout"
            )
        logger.warning(
            "\n  ABORT: %s — %s.\n"
            "  Stopping test and reporting available results.",
            ", ".join(parts), f"{total_bad} request(s) failed",
        )
        return True
