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

"""Console reporting — tables, resources, pool reuse, and disconnections."""

import logging
from typing import List
from typing import Tuple

logger = logging.getLogger(__name__)

SEPARATOR_WIDTH = 60


class TableFormatter:
    """Formats and logs aligned tables."""

    @staticmethod
    def log_table(header, rows):
        """Log an aligned table given a header list and rows."""
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


class ResourceReporter:
    """Builds and logs server and client resource delta tables."""

    @staticmethod
    def build_resource_row(stage_label, before, after) -> Tuple:
        """Build a resource summary row from before/after snapshots."""
        rss_delta = after.get("rss") - before.get("rss")
        thread_delta = after.get("threads") - before.get("threads")
        return (
            str(stage_label),
            f"{before.get('rss'):.1f}M",
            f"{after.get('rss'):.1f}M",
            f"+{rss_delta:.1f}M",
            str(after.get("fds")),
            f"{before.get('threads')} -> {after.get('threads')}",
            f"+{thread_delta}",
            str(after.get("connections")),
            f"{after.get('cpu'):.1f}%",
            str(after.get("children")),
        )

    @staticmethod
    def build_client_row(stage_label, before, peak, settled) -> Tuple:
        """Build a client resource row from before/peak/settled."""
        rss_delta = settled.get("rss") - before.get("rss")
        peak_rss = f"{peak.get('rss'):.1f}M" if peak else "-"
        return (
            str(stage_label),
            f"{before.get('rss'):.1f}M",
            peak_rss,
            f"{settled.get('rss'):.1f}M",
            f"{rss_delta:+.1f}M",
            f"{settled.get('cpu'):.1f}%",
            str(settled.get("fds")),
            str(settled.get("threads")),
        )

    @staticmethod
    def log_resource_analysis(
            resource_rows, total_client_reqs, total_server_calls,
    ):
        """Log server resource analysis table."""
        if not resource_rows:
            return
        resource_header = [
            "Concurrent", "Before RSS", "Settled RSS", "RSS Delta",
            "FDs", "Threads", "Thread Delta",
            "Conns", "CPU%", "Children",
        ]
        logger.info("\n%s", "=" * SEPARATOR_WIDTH)
        if total_server_calls > 0:
            logger.info(
                "  SERVER RESOURCE ANALYSIS"
                " (%s client requests, %s server calls)",
                total_client_reqs, total_server_calls,
            )
        else:
            logger.info(
                "  SERVER RESOURCE ANALYSIS"
                " (%s total requests)",
                total_client_reqs,
            )
        logger.info("=" * SEPARATOR_WIDTH)
        TableFormatter.log_table(resource_header, resource_rows)
        ResourceReporter._log_resource_deltas(resource_rows)

    @staticmethod
    def _log_resource_deltas(resource_rows):
        """Log overall resource deltas if enough data points."""
        if len(resource_rows) < 2:
            return
        first = resource_rows[0]
        last = resource_rows[-1]
        logger.info(
            "\n  Server overall deltas (first stage vs last stage):",
        )
        logger.info(
            "    RSS:         +%.1f MB",
            float(last[2].rstrip("M")) - float(first[1].rstrip("M")),
        )
        logger.info(
            "    FDs:         +%s",
            int(last[4]) - int(first[4]),
        )
        logger.info(
            "    Threads:     +%s",
            int(last[5].split(" -> ")[1])
            - int(first[5].split(" -> ")[0]),
        )
        logger.info(
            "    Connections: +%s",
            int(last[7]) - int(first[7]),
        )
        logger.info(
            "    Children:    +%s",
            int(last[9]) - int(first[9]),
        )

    @staticmethod
    def log_client_analysis(client_rows, total_client_reqs):
        """Log client resource analysis table."""
        if not client_rows:
            return
        client_header = [
            "Concurrent", "Before RSS", "Peak RSS",
            "Settled RSS", "RSS Delta",
            "CPU%", "FDs", "Threads",
        ]
        logger.info("\n%s", "=" * SEPARATOR_WIDTH)
        logger.info(
            "  CLIENT RESOURCE ANALYSIS"
            " (%s total requests)",
            total_client_reqs,
        )
        logger.info("=" * SEPARATOR_WIDTH)
        TableFormatter.log_table(client_header, client_rows)
        ResourceReporter._log_client_deltas(client_rows)

    @staticmethod
    def _log_client_deltas(client_rows):
        """Log overall client resource deltas if enough data points."""
        if len(client_rows) < 2:
            return
        first = client_rows[0]
        last = client_rows[-1]
        logger.info(
            "\n  Client overall deltas (first stage vs last stage):",
        )
        logger.info(
            "    RSS:     +%.1f MB",
            float(last[3].rstrip("M"))
            - float(first[1].rstrip("M")),
        )
        logger.info(
            "    FDs:     +%s",
            int(last[6]) - int(first[6]),
        )
        logger.info(
            "    Threads: +%s",
            int(last[7]) - int(first[7]),
        )


class PoolAnalyzer:
    """Analyzes executor thread pool reuse across load test stages."""

    # pylint: disable=too-many-locals
    @staticmethod
    def log_pool_reuse_analysis(stage_summaries):
        """Log executor pool reuse analysis across stages."""
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

        logger.info("\n%s", "=" * SEPARATOR_WIDTH)
        logger.info("  EXECUTOR POOL REUSE ANALYSIS")
        logger.info("=" * SEPARATOR_WIDTH)

        header = [
            "Batch", "Server Calls", "New Threads",
            "Peak Threads", "Reused", "Reuse%",
            "Pool Avail", "Exec/Req",
        ]
        rows: List[Tuple] = []
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
                stage.get("after_threads")
                - stage.get("before_threads"), 0,
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


class DisconnectionReporter:
    """Aggregates and logs client disconnection analysis."""

    @staticmethod
    def log_disconnection_summary(stage_summaries):
        """Log aggregate client disconnection report."""
        all_disconnections = []
        for idx, stage in enumerate(stage_summaries):
            for disc in stage.get("disconnections") or []:
                disc_copy = dict(disc)
                disc_copy.update({"batch": idx + 1})
                all_disconnections.append(disc_copy)
        if not all_disconnections:
            return
        logger.info("\n%s", "=" * SEPARATOR_WIDTH)
        logger.info(
            "  CLIENT DISCONNECTIONS (%s detected in server log)",
            len(all_disconnections),
        )
        logger.info("=" * SEPARATOR_WIDTH)
        for disc in all_disconnections:
            logger.info(
                "  Batch %s: %s — %s still processing at disconnect",
                disc.get("batch", "?"),
                disc.get("request_id", "unknown"),
                disc.get("agent", "unknown"),
            )
        logger.info(
            "\n  These requests had their client disconnect"
            "\n  before the server finished. The server detected the"
            "\n  disconnection and cancelled in-flight tasks."
            "\n  If unexpected, consider increasing --idle-timeout.",
        )
