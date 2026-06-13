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

"""Executor pool reuse analysis across load test stages."""

import logging

logger = logging.getLogger(__name__)


class PoolAnalyzer:
    """Analyzes executor thread pool reuse across load test stages."""

    # pylint: disable=too-many-locals
    @staticmethod
    def log_pool_reuse_analysis(stage_summaries):
        """Log executor pool reuse analysis across stages.

        Each streaming_chat server call allocates one AsyncioExecutor via
        get_executor(). New executors spawn a thread; reused ones do not.
        By comparing thread deltas to total server calls we can estimate
        how effectively the pool is reusing executors between batches.
        """
        stages_with_data = [
            s for s in stage_summaries
            if s.get("before_threads") is not None
            and s.get("after_threads") is not None
            and s.get("total_started") is not None
            and s.get("total_started") > 0
        ]
        if not stages_with_data:
            return

        base_threads = stages_with_data[0].get("before_threads")

        logger.info("\n%s", "=" * 60)
        logger.info("  EXECUTOR POOL REUSE ANALYSIS")
        logger.info("=" * 60)

        header = [
            "Batch", "Server Calls", "New Threads",
            "Peak Threads", "Reused", "Reuse%",
            "Pool Avail", "Exec/Req",
        ]
        rows = []
        total_new_threads = 0

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
            pool_avail = max(before_threads - base_threads, 0)

            primary = (
                stage.get("primary_started") or stage.get("concurrent")
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

        col_widths = [len(h) for h in header]
        for row in rows:
            for i, val in enumerate(row):
                col_widths[i] = max(col_widths[i], len(str(val)))
        fmt = "  ".join(f"{{:>{w}}}" for w in col_widths)
        logger.info("%s", fmt.format(*header))
        logger.info(
            "%s", "-" * (sum(col_widths) + 2 * (len(header) - 1)),
        )
        for row in rows:
            logger.info("%s", fmt.format(*row))

        PoolAnalyzer._log_pool_diagnostics(
            stages_with_data, total_new_threads,
        )

    @staticmethod
    def _log_pool_diagnostics(stages_with_data, total_new_threads):
        """Log summary diagnostics for pool reuse if enough data."""
        if len(stages_with_data) < 2:
            return
        first_reuse = 0.0
        last_reuse = 0.0
        for idx, stage in enumerate(stages_with_data):
            server_calls = stage.get("total_started")
            new_t = max(
                stage.get("after_threads") - stage.get("before_threads"),
                0,
            )
            reused = max(server_calls - new_t, 0)
            pct = (
                (reused / server_calls * 100.0)
                if server_calls > 0 else 0.0
            )
            if idx == 0:
                first_reuse = pct
            last_reuse = pct

        first_demand = max(
            stages_with_data[0].get("after_threads")
            - stages_with_data[0].get("before_threads"), 0,
        )
        logger.info(
            "\n  Pool reuse: %.1f%% (batch 1) -> %.1f%% (batch %d)",
            first_reuse, last_reuse, len(stages_with_data),
        )
        if total_new_threads > first_demand > 0:
            excess = total_new_threads - first_demand
            logger.info(
                "  WARNING: %d new threads created across all batches, "
                "but batch 1 demand was only %d.",
                total_new_threads, first_demand,
            )
            logger.info(
                "           %d excess threads indicate pool lock "
                "contention in return_executor().",
                excess,
            )
            logger.info(
                "           cancel_current_tasks() holds the pool lock "
                "for up to 5s, blocking reuse.",
            )
