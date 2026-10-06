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

"""Builds and logs server and client resource delta tables."""

import logging
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

from tests.load_tests.config import SEPARATOR_WIDTH
from tests.load_tests.reporting.table_formatter import TableFormatter

# (display_row, before_snapshot, after_snapshot)
ServerResourceRow = Tuple[tuple, Dict[str, Any], Dict[str, Any]]

# (display_row, before_snapshot, peak_snapshot, settled_snapshot)
ClientResourceRow = Tuple[
    tuple, Dict[str, Any], Dict[str, Any], Dict[str, Any],
]

logger: logging.Logger = logging.getLogger(__name__)


class ResourceReporter:
    """Builds and logs server and client resource delta tables.

    Accumulates resource rows during the test run, then logs
    the complete analysis tables at the end.
    """

    def __init__(self) -> None:
        self._resource_rows: List[ServerResourceRow] = []
        self._client_rows: List[ClientResourceRow] = []

    @property
    def resource_rows(self) -> List[ServerResourceRow]:
        """
        Return the accumulated server resource rows.

        :return: A copy of the server resource rows
        """
        return list(self._resource_rows)

    @property
    def client_rows(self) -> List[ClientResourceRow]:
        """
        Return the accumulated client resource rows.

        :return: A copy of the client resource rows
        """
        return list(self._client_rows)

    def add_resource_row(self, stage_label: str, before_snapshot: Dict[str, Any],
                         after_snapshot: Dict[str, Any]) -> ServerResourceRow:
        """Build and store a server resource row from before/after snapshots.

        Returns (display_row, before_snapshot, after_snapshot) so that
        delta calculations can use raw numeric values instead of
        reverse-parsing formatted strings.

        :param stage_label: Label shown in the first column
        :param before_snapshot: Server process snapshot taken before the stage
        :param after_snapshot: Server process snapshot taken after the stage
        :return: (display_row, before_snapshot, after_snapshot)
        """
        rss_delta_megabytes: float = after_snapshot.get("rss") - before_snapshot.get("rss")
        thread_delta: int = after_snapshot.get("threads") - before_snapshot.get("threads")
        display: Tuple[str, ...] = (
            str(stage_label),
            f"{before_snapshot.get('rss'):.1f}M",
            f"{after_snapshot.get('rss'):.1f}M",
            f"{rss_delta_megabytes:+.1f}M",
            str(after_snapshot.get("fds")),
            f"{before_snapshot.get('threads')} -> {after_snapshot.get('threads')}",
            f"{thread_delta:+d}",
            str(after_snapshot.get("connections")),
            f"{after_snapshot.get('cpu'):.1f}%",
            str(after_snapshot.get("children")),
        )
        row: ServerResourceRow = (display, before_snapshot, after_snapshot)
        self._resource_rows.append(row)
        return row

    def add_client_row(self, stage_label: str, before_snapshot: Dict[str, Any], peak_snapshot: Optional[Dict[str, Any]],
                       settled_snapshot: Dict[str, Any]) -> ClientResourceRow:
        """Build and store a client resource row from before/peak/settled.

        Returns (display_row, before_snapshot, peak_snapshot,
        settled_snapshot) so that delta calculations and JSON export
        can use raw numeric values.

        :param stage_label: Label shown in the first column
        :param before_snapshot: Client process snapshot taken before the stage
        :param peak_snapshot: Client process snapshot at peak RSS during the stage, or None
        :param settled_snapshot: Client process snapshot taken after the stage settled
        :return: (display_row, before_snapshot, peak_snapshot or {}, settled_snapshot)
        """
        rss_delta_megabytes: float = settled_snapshot.get("rss") - before_snapshot.get("rss")
        peak_rss_text: str = f"{peak_snapshot.get('rss'):.1f}M" if peak_snapshot else "-"
        display: Tuple[str, ...] = (
            str(stage_label),
            f"{before_snapshot.get('rss'):.1f}M",
            peak_rss_text,
            f"{settled_snapshot.get('rss'):.1f}M",
            f"{rss_delta_megabytes:+.1f}M",
            f"{settled_snapshot.get('cpu'):.1f}%",
            str(settled_snapshot.get("fds")),
            str(settled_snapshot.get("threads")),
        )
        row: ClientResourceRow = (display, before_snapshot, peak_snapshot or {}, settled_snapshot)
        self._client_rows.append(row)
        return row

    # Placeholder row (Component + 11 metric columns) shown when a
    # component produced no data at all.
    _NA_METRICS: Tuple[str, ...] = ("na",) * 11

    def log_combined_analysis(self, total_client_requests: int, total_server_calls: int) -> None:
        """Log one combined server-app + client-app resource table.

        Server-app and client-app rows share a single table.  Columns
        that don't apply to a component — or a component that produced
        no data (no local server, or the server-only mode's absent
        client) — show ``na``.

        :param total_client_requests: Client requests sent across all stages
        :param total_server_calls: Server calls across all stages; 0 leaves it out of the title
        """
        if not self._resource_rows and not self._client_rows:
            return
        header: List[str] = [
            "Component", "Concurrent", "Before RSS", "Peak RSS",
            "Settled RSS", "RSS Delta", "CPU%", "FDs",
            "Threads", "Thread Delta", "Conns", "Children",
        ]
        rows: List[tuple] = self._combined_server_rows() + self._combined_client_rows()
        logger.info("\n%s", "=" * SEPARATOR_WIDTH)
        if total_server_calls > 0:
            logger.info(
                "  RESOURCE ANALYSIS"
                " (%s client requests, %s server calls)",
                total_client_requests, total_server_calls,
            )
        else:
            logger.info(
                "  RESOURCE ANALYSIS (%s total requests)",
                total_client_requests,
            )
        logger.info("=" * SEPARATOR_WIDTH)
        TableFormatter.log_table(header, rows)
        self._log_resource_deltas()
        self._log_client_deltas()

    def _combined_server_rows(self) -> List[tuple]:
        """
        Server-app rows for the combined table (na when absent).

        :return: One row per stage, or one row of na when there is no server data
        """
        if not self._resource_rows:
            return [("Server app",) + self._NA_METRICS]
        rows: List[tuple] = []
        for display, unused_before_snapshot, unused_after_snapshot in self._resource_rows:
            # display: (concurrent, before_rss, settled_rss, rss_delta,
            #   fds, threads, thread_delta, conns, cpu, children)
            rows.append((
                "Server app", display[0], display[1], "na",
                display[2], display[3], display[8], display[4],
                display[5], display[6], display[7], display[9],
            ))
        return rows

    def _combined_client_rows(self) -> List[tuple]:
        """
        Client-app rows for the combined table (na when absent).

        :return: One row per stage, or one row of na when there is no client data
        """
        if not self._client_rows:
            return [("Client app",) + self._NA_METRICS]
        rows: List[tuple] = []
        for row in self._client_rows:
            display: Tuple[str, ...] = row[0]
            # display: (concurrent, before_rss, peak_rss, settled_rss,
            #   rss_delta, cpu, fds, threads)
            rows.append((
                "Client app", display[0], display[1], display[2],
                display[3], display[4], display[5], display[6],
                display[7], "na", "na", "na",
            ))
        return rows

    def _log_resource_deltas(self) -> None:
        """Log overall resource deltas if enough data points."""
        if len(self._resource_rows) < 2:
            return
        first_before_snapshot: Dict[str, Any] = self._resource_rows[0][1]
        last_after_snapshot: Dict[str, Any] = self._resource_rows[-1][2]
        self._log_snapshot_deltas(
            "Server", first_before_snapshot, last_after_snapshot,
            fields=[
                ("RSS", "rss", "%.1f MB"),
                ("FDs", "fds", "%s"),
                ("Threads", "threads", "%s"),
                ("Connections", "connections", "%s"),
                ("Children", "children", "%s"),
            ],
        )

    def _log_client_deltas(self) -> None:
        """Log overall client resource deltas if enough data points."""
        if len(self._client_rows) < 2:
            return
        first_before_snapshot: Dict[str, Any] = self._client_rows[0][1]
        last_settled_snapshot: Dict[str, Any] = self._client_rows[-1][3]
        self._log_snapshot_deltas(
            "Client", first_before_snapshot, last_settled_snapshot,
            fields=[
                ("RSS", "rss", "%.1f MB"),
                ("FDs", "fds", "%s"),
                ("Threads", "threads", "%s"),
            ],
        )

    @staticmethod
    def _log_snapshot_deltas(label: str, before_snapshot: Dict[str, Any], after_snapshot: Dict[str, Any],
                             fields: List[Tuple[str, str, str]]) -> None:
        """
        Log deltas between two ResourceSnapshots.

        :param label: Component name shown in the heading
        :param before_snapshot: Snapshot from the first stage
        :param after_snapshot: Snapshot from the last stage
        :param fields: (display name, snapshot key, % format) of each field to log
        """
        maximum_name_length: int = max(len(name) for name, _, _ in fields)
        logger.info(
            "\n  %s overall deltas (first stage vs last stage):",
            label,
        )
        for name, key, format_pattern in fields:
            delta: float = after_snapshot.get(key) - before_snapshot.get(key)
            padded: str = f"{name}:".ljust(maximum_name_length + 1)
            formatted: str = format_pattern % abs(delta)
            sign: str = "+" if delta >= 0 else "-"
            logger.info(
                "    %s %s%s", padded, sign, formatted,
            )
