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

"""Summary reporting — ramp-up and overall results."""

import logging

from tests.load_tests.config import STATUS_CREATED
from tests.load_tests.config import STATUS_FAILED
from tests.load_tests.config import STATUS_KILLED
from tests.load_tests.config import STATUS_TIMEOUT
from tests.load_tests.reporting.table_formatter import TableFormatter

logger = logging.getLogger(__name__)

SEPARATOR_WIDTH = 60


class SummaryReporter:
    """Logs ramp-up and overall results across all stages."""

    @staticmethod
    def log_ramp_summary(stage_summaries):
        """Log the ramp-up summary table across all stages."""
        logger.info("\n%s", "=" * SEPARATOR_WIDTH)
        logger.info("  RAMP-UP SUMMARY")
        logger.info("=" * SEPARATOR_WIDTH)

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
                    if pri_started is not None
                    and total_started is not None
                    else "-"
                )
                row += (
                    str(pri_started)
                    if pri_started is not None else "-",
                    str(pri_finished)
                    if pri_finished is not None else "-",
                    internal,
                )
            rows.append(row)
        TableFormatter.log_table(header, rows)

    @staticmethod
    def log_overall_results(stage_summaries):
        """Log overall results across all stages."""
        total_created = 0
        total_failed = 0
        total_timeout = 0
        total_killed = 0
        total_time = 0.0
        total_retries = 0

        for summary in stage_summaries:
            counts = summary.get("counts", {})
            total_created += counts.get(STATUS_CREATED, 0)
            total_failed += counts.get(STATUS_FAILED, 0)
            total_timeout += counts.get(STATUS_TIMEOUT, 0)
            total_killed += counts.get(STATUS_KILLED, 0)
            total_time += summary.get("elapsed", 0)
            total_retries += summary.get("total_retries", 0)

        total_sent = (
            total_created + total_failed + total_timeout + total_killed
        )

        logger.info("\n%s", "=" * SEPARATOR_WIDTH)
        logger.info("  OVERALL RESULTS")
        logger.info("=" * SEPARATOR_WIDTH)
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
            total_requests = sum(
                s.get("concurrent", 0) for s in stage_summaries
            )
            amplification = (
                (total_requests + total_retries) / total_requests
                if total_requests > 0 else 1.0
            )
            logger.info("\n  Overall max_attempts retry totals:")
            logger.info("    Total retries:   %s", total_retries)
            logger.info(
                "    Amplification:   %.2fx", amplification,
            )
