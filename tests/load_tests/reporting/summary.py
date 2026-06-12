"""Summary reporting — ramp-up and overall results."""

import logging
from typing import Any
from typing import Dict
from typing import List

from tests.load_tests.config import STATUS_CREATED
from tests.load_tests.config import STATUS_FAILED
from tests.load_tests.config import STATUS_TIMEOUT
from tests.load_tests.config import STATUS_KILLED
from tests.load_tests.reporting.table_utils import log_table

logger = logging.getLogger(__name__)


def log_ramp_summary(stage_summaries):
    """Log the ramp-up summary table across all stages."""
    logger.info("\n%s", "=" * 60)
    logger.info("  RAMP-UP SUMMARY")
    logger.info("=" * 60)

    has_server_counts = any(
        summary.get("primary_started") is not None
        for summary in stage_summaries
    )
    header = [
        "Stage", "Concurrent", "Created", "Failed",
        "Timeout", "Killed", "Retries", "Amplification",
        "Duration",
    ]
    if has_server_counts:
        header.extend(["Recv", "Done", "Internal"])
    rows = []
    for summary in stage_summaries:
        counts = summary.get("counts", {})
        row = (
            str(summary.get("stage")),
            str(summary.get("concurrent")),
            str(counts.get(STATUS_CREATED, 0)),
            str(counts.get(STATUS_FAILED, 0)),
            str(counts.get(STATUS_TIMEOUT, 0)),
            str(counts.get(STATUS_KILLED, 0)),
            str(summary.get("total_retries", 0)),
            f"{summary.get('amplification', 1.0):.2f}x",
            f"{summary.get('elapsed', 0):.1f}s",
        )
        if has_server_counts:
            pri_started = summary.get("primary_started")
            pri_finished = summary.get("primary_finished")
            total_started = summary.get("total_started")
            internal = (
                str(total_started - pri_started)
                if pri_started is not None and total_started is not None
                else "-"
            )
            row += (
                str(pri_started) if pri_started is not None else "-",
                str(pri_finished) if pri_finished is not None else "-",
                internal,
            )
        rows.append(row)
    log_table(header, rows)


def log_overall_results(stage_summaries):
    """Log overall results across all stages."""
    total_created = 0
    total_failed = 0
    total_timeout = 0
    total_killed = 0
    total_time = 0.0
    total_retries = 0
    total_requests = 0
    all_results: List[Dict[str, Any]] = []

    for summary in stage_summaries:
        counts = summary.get("counts", {})
        total_created += counts.get(STATUS_CREATED, 0)
        total_failed += counts.get(STATUS_FAILED, 0)
        total_timeout += counts.get(STATUS_TIMEOUT, 0)
        total_killed += counts.get(STATUS_KILLED, 0)
        total_time += summary.get("elapsed", 0)
        total_retries += summary.get("total_retries", 0)
        total_requests += summary.get("concurrent", 0)
        all_results.extend(summary.get("results", []))

    total_sent = total_created + total_failed + total_timeout + total_killed

    logger.info("\n%s", "=" * 60)
    logger.info("  OVERALL RESULTS")
    logger.info("=" * 60)
    logger.info("  Total requests: %s", total_sent)
    logger.info("    Created:   %s", total_created)
    logger.info("    Failed:    %s", total_failed)
    logger.info("    Timed out: %s", total_timeout)
    logger.info("    Killed:    %s", total_killed)
    logger.info("  Total time:  %.2fs", total_time)
    if total_sent > 0:
        logger.info(
            "  Avg per request: %.2fs", total_time / total_sent,
        )

    if total_retries > 0:
        amplification = (
            (total_requests + total_retries) / total_requests
            if total_requests > 0 else 1.0
        )
        logger.info("\n  Overall max_attempts retry totals:")
        logger.info("    Total retries:   %s", total_retries)
        logger.info("    Amplification:   %.2fx", amplification)

    # Token usage summary
    token_totals = [r.get("total_tokens", 0) for r in all_results if r.get("total_tokens")]
    if token_totals:
        token_totals_sorted = sorted(token_totals)
        total_all = sum(token_totals)
        avg_tokens = total_all / len(token_totals)
        p50 = token_totals_sorted[len(token_totals_sorted) // 2]
        p90_idx = int(len(token_totals_sorted) * 0.9)
        p90 = token_totals_sorted[min(p90_idx, len(token_totals_sorted) - 1)]
        total_prompt = sum(r.get("prompt_tokens", 0) for r in all_results)
        total_comp = sum(r.get("completion_tokens", 0) for r in all_results)
        total_llm = sum(r.get("llm_calls", 0) for r in all_results)
        logger.info("\n  Token usage:")
        logger.info("    Total tokens:    %s", f"{total_all:,}")
        logger.info("    Avg per request: %s", f"{int(avg_tokens):,}")
        logger.info("    P50:             %s", f"{p50:,}")
        logger.info("    P90:             %s", f"{p90:,}")
        logger.info("    Max:             %s", f"{max(token_totals):,}")
        logger.info("    Prompt tokens:   %s (%.0f%%)",
                    f"{total_prompt:,}",
                    100 * total_prompt / total_all if total_all else 0)
        logger.info("    Completion:      %s (%.0f%%)",
                    f"{total_comp:,}",
                    100 * total_comp / total_all if total_all else 0)
        logger.info("    LLM calls:       %s (avg %.1f/request)",
                    total_llm, total_llm / len(token_totals))

    created = [r for r in all_results if r.get("status") == STATUS_CREATED]
    if created:
        logger.info("\n  Networks/requests successfully created:")
        for result in created:
            name = result.get("agent_network_name") or result.get("network_name")
            reservation = result.get("reservation_id")
            if name:
                logger.info(
                    "    %s (reservation: %s, %.2fs)",
                    name, reservation or "none", result.get("elapsed"),
                )
            else:
                logger.info(
                    "    request completed (%.2fs)", result.get("elapsed"),
                )
