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

"""Builds and logs server and client resource delta tables."""

import logging
from typing import List
from typing import Tuple

from tests.load_tests.config import ResourceSnapshot
from tests.load_tests.config import SEPARATOR_WIDTH
from tests.load_tests.reporting.table_formatter import TableFormatter

logger = logging.getLogger(__name__)


class ResourceReporter:
    """Builds and logs server and client resource delta tables.

    Accumulates resource rows during the test run, then logs
    the complete analysis tables at the end.
    """

    def __init__(self) -> None:
        self._resource_rows: List[Tuple] = []
        self._client_rows: List[Tuple] = []

    @property
    def resource_rows(self) -> List[Tuple]:
        """Return the accumulated server resource rows."""
        return self._resource_rows

    @property
    def client_rows(self) -> List[Tuple]:
        """Return the accumulated client resource rows."""
        return self._client_rows

    def add_resource_row(
            self, stage_label, before, after,
    ) -> Tuple[tuple, ResourceSnapshot, ResourceSnapshot]:
        """Build and store a server resource row from before/after snapshots.

        Returns (display_row, before_snapshot, after_snapshot) so that
        delta calculations can use raw numeric values instead of
        reverse-parsing formatted strings.
        """
        rss_delta = after.get("rss") - before.get("rss")
        thread_delta = after.get("threads") - before.get("threads")
        display = (
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
        row = (display, before, after)
        self._resource_rows.append(row)
        return row

    def add_client_row(
            self, stage_label, before, peak, settled,
    ) -> Tuple[tuple, ResourceSnapshot, ResourceSnapshot,
               ResourceSnapshot]:
        """Build and store a client resource row from before/peak/settled.

        Returns (display_row, before_snapshot, peak_snapshot,
        settled_snapshot) so that delta calculations and JSON export
        can use raw numeric values.
        """
        rss_delta = settled.get("rss") - before.get("rss")
        peak_rss = f"{peak.get('rss'):.1f}M" if peak else "-"
        display = (
            str(stage_label),
            f"{before.get('rss'):.1f}M",
            peak_rss,
            f"{settled.get('rss'):.1f}M",
            f"{rss_delta:+.1f}M",
            f"{settled.get('cpu'):.1f}%",
            str(settled.get("fds")),
            str(settled.get("threads")),
        )
        row = (display, before, peak or {}, settled)
        self._client_rows.append(row)
        return row

    def log_resource_analysis(
            self, total_client_reqs, total_server_calls,
    ) -> None:
        """Log server resource analysis table."""
        if not self._resource_rows:
            return
        display_rows = [row[0] for row in self._resource_rows]
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
        TableFormatter.log_table(resource_header, display_rows)
        self._log_resource_deltas()

    def _log_resource_deltas(self) -> None:
        """Log overall resource deltas if enough data points."""
        if len(self._resource_rows) < 2:
            return
        first_before = self._resource_rows[0][1]
        last_after = self._resource_rows[-1][2]
        logger.info(
            "\n  Server overall deltas (first stage vs last stage):",
        )
        logger.info(
            "    RSS:         +%.1f MB",
            last_after.get("rss") - first_before.get("rss"),
        )
        logger.info(
            "    FDs:         +%s",
            last_after.get("fds") - first_before.get("fds"),
        )
        logger.info(
            "    Threads:     +%s",
            last_after.get("threads") - first_before.get("threads"),
        )
        logger.info(
            "    Connections: +%s",
            last_after.get("connections")
            - first_before.get("connections"),
        )
        logger.info(
            "    Children:    +%s",
            last_after.get("children")
            - first_before.get("children"),
        )

    def log_client_analysis(self, total_client_reqs) -> None:
        """Log client resource analysis table."""
        if not self._client_rows:
            return
        display_rows = [row[0] for row in self._client_rows]
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
        TableFormatter.log_table(client_header, display_rows)
        self._log_client_deltas()

    def _log_client_deltas(self) -> None:
        """Log overall client resource deltas if enough data points."""
        if len(self._client_rows) < 2:
            return
        first_before = self._client_rows[0][1]
        last_settled = self._client_rows[-1][3]
        logger.info(
            "\n  Client overall deltas (first stage vs last stage):",
        )
        logger.info(
            "    RSS:     +%.1f MB",
            last_settled.get("rss") - first_before.get("rss"),
        )
        logger.info(
            "    FDs:     +%s",
            last_settled.get("fds") - first_before.get("fds"),
        )
        logger.info(
            "    Threads: +%s",
            last_settled.get("threads")
            - first_before.get("threads"),
        )
