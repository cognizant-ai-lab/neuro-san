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

"""Analyzes executor thread pool reuse across load test stages."""

import logging
from typing import List

from tests.load_tests.config import SEPARATOR_WIDTH
from tests.load_tests.reporting.table_formatter import TableFormatter

logger = logging.getLogger(__name__)


class PoolAnalyzer:
    """Analyzes executor thread pool reuse across load test stages.

    Holds the collected stage summaries for analysis.
    """

    def __init__(self, stage_summaries) -> None:
        self._summaries = stage_summaries

    # pylint: disable=too-many-locals
    def log_pool_reuse_analysis(self) -> None:
        """Log executor pool reuse analysis across stages."""
        stages_with_data = [
            s for s in self._summaries
            if s.get("before_threads") is not None
            and s.get("after_threads") is not None
            and s.get("total_started") is not None
            and s.get("total_started") > 0
        ]
        if not stages_with_data:
            return

        base_threads = stages_with_data[0].get("before_threads")

        logger.info("\n%s", "=" * SEPARATOR_WIDTH)
        logger.info("  EXECUTOR POOL REUSE ANALYSIS")
        logger.info("=" * SEPARATOR_WIDTH)

        header = [
            "Batch", "Server Calls", "New Threads",
            "Peak Threads", "Reused", "Reuse%",
            "Pool Avail", "Exec/Req",
        ]
        rows: List[tuple] = []
        total_new_threads = 0
        reuse_pcts: List[float] = []

        for idx, stage in enumerate(stages_with_data):
            batch_num = idx + 1
            server_calls = stage.get("total_started")
            before_threads = stage.get("before_threads")
            after_threads = stage.get("after_threads")
            new_threads = max(after_threads - before_threads, 0)
            total_new_threads += new_threads
            reused = max(server_calls - new_threads, 0)
            reuse_pct = (
                (reused / server_calls * 100.0)
                if server_calls > 0 else 0.0
            )
            reuse_pcts.append(reuse_pct)
            pool_avail = max(before_threads - base_threads, 0)

            primary = (
                stage.get("primary_started")
                or stage.get("concurrent")
            )
            exec_per_req = (
                server_calls / primary if primary > 0 else 0.0
            )

            peak_t = stage.get("peak_threads")
            peak_str = str(peak_t) if peak_t is not None else "-"

            rows.append((
                str(batch_num),
                str(server_calls),
                f"+{new_threads}",
                peak_str,
                str(reused),
                f"{reuse_pct:.1f}%",
                str(pool_avail),
                f"{exec_per_req:.1f}",
            ))

        TableFormatter.log_table(header, rows)

        first_demand = max(
            stages_with_data[0].get("after_threads")
            - stages_with_data[0].get("before_threads"), 0,
        )
        self._log_pool_diagnostics(
            reuse_pcts, total_new_threads,
            first_demand=first_demand,
        )

    @staticmethod
    def _log_pool_diagnostics(
            reuse_pcts, total_new_threads, *,
            first_demand,
    ) -> None:
        """Log summary diagnostics for pool reuse."""
        if len(reuse_pcts) < 2:
            return
        logger.info(
            "\n  Pool reuse: %.1f%% (batch 1) -> %.1f%% (batch %d)",
            reuse_pcts[0], reuse_pcts[-1], len(reuse_pcts),
        )
        if total_new_threads > first_demand > 0:
            excess = total_new_threads - first_demand
            logger.info(
                "  WARNING: %d new threads created across all "
                "batches, but batch 1 demand was only %d.",
                total_new_threads, first_demand,
            )
            logger.info(
                "           %d excess threads indicate pool lock "
                "contention in return_executor().",
                excess,
            )
            logger.info(
                "           cancel_current_tasks() holds the pool "
                "lock for up to 5s, blocking reuse.",
            )
