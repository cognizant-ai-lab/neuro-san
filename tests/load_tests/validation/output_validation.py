"""Output validation — result counting and server-side request verification."""

import logging
from typing import Dict

from tests.load_tests.config import STATUS_CREATED
from tests.load_tests.config import STATUS_FAILED
from tests.load_tests.config import STATUS_TIMEOUT
from tests.load_tests.config import STATUS_KILLED

logger = logging.getLogger(__name__)


class OutputValidator:
    """Counts results and logs server-side request verification."""

    @staticmethod
    def count_results(results) -> Dict[str, int]:
        """Count results by status type."""
        counts = {
            STATUS_CREATED: 0,
            STATUS_FAILED: 0,
            STATUS_TIMEOUT: 0,
            STATUS_KILLED: 0,
        }
        for result in results:
            status = result.get("status", STATUS_FAILED)
            counts[status] = counts.get(status, 0) + 1
        return counts

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    @staticmethod
    def log_stage_results(actual_requests, counts, elapsed, timeout,
                          idle_timeout, skip_reservation_check=False):
        """Log per-stage summary of request results."""
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
        logger.info(
            "  Duration: %.2fs | Avg: %.2fs per request",
            elapsed,
            elapsed / actual_requests if actual_requests else 0,
        )

    @staticmethod
    def log_retry_activity(retries, total_retries, actual_requests):
        """Log retry activity from server log."""
        # Lazy import to avoid circular dependency: config -> validation
        from tests.load_tests.config import RETRY_ERROR_TYPES  # pylint: disable=import-outside-toplevel
        logger.info(
            "\n  max_attempts retry activity (from server log):",
        )
        for error_type in RETRY_ERROR_TYPES:
            count = retries.get(error_type, 0)
            logger.info("    %s retries: %s", error_type, count)
        logger.info("    Total retries:  %s", total_retries)
        amplification = (
            (actual_requests + total_retries) / actual_requests
            if actual_requests > 0 else 1.0
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
    ):
        """Log server-side request validation from log counts."""
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
    def log_disconnections(disconnections):
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
            logger.warning(
                "    %s: %s still running at disconnect",
                req_id, agent,
            )
