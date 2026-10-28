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

from logging import Logger
from logging import getLogger
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from tests.load_tests.reporting.formatters import Formatters
from tests.load_tests.reporting.table_formatter import TableFormatter

# Keys "display" (table cells), "before" and "after" (server snapshots)
ServerResourceRow = Dict[str, Any]

# Keys "display" (table cells), "before", "peak" and "settled" (client snapshots)
ClientResourceRow = Dict[str, Any]


class ResourceReporter:
    """
    Builds and logs server and client resource delta tables.

    Accumulates resource rows during the test run, then logs
    the complete analysis tables at the end.
    """

    def __init__(self) -> None:
        """
        Start with no server or client resource rows.
        """
        self.logger: Logger = getLogger(self.__class__.__name__)
        self._resource_rows: List[ServerResourceRow] = []
        self._client_rows: List[ClientResourceRow] = []

    def get_resource_snapshots(self) -> List[Dict[str, Any]]:
        """
        Return the snapshots of each server resource row, for the results JSON.

        :return: One dict per server row with keys "before" and "after"
        """
        snapshots: List[Dict[str, Any]] = []
        row: ServerResourceRow
        # Keep the snapshots of each row and drop its table cells.
        for row in self._resource_rows:
            snapshot: Dict[str, Any] = {
                "before": row.get("before"),
                "after": row.get("after"),
            }
            snapshots.append(snapshot)
        return snapshots

    def get_client_snapshots(self) -> List[Dict[str, Any]]:
        """
        Return the snapshots of each client resource row, for the results JSON.

        :return: One dict per client row with keys "before", "peak" and "settled"
        """
        snapshots: List[Dict[str, Any]] = []
        row: ClientResourceRow
        # Keep the snapshots of each row and drop its table cells.
        for row in self._client_rows:
            snapshot: Dict[str, Any] = {
                "before": row.get("before"),
                "peak": row.get("peak"),
                "settled": row.get("settled"),
            }
            snapshots.append(snapshot)
        return snapshots

    def add_resource_row(self, stage_label: str, before_snapshot: Dict[str, Any],
                         after_snapshot: Dict[str, Any]) -> ServerResourceRow:
        """
        Build and store a server resource row from before/after snapshots.

        The row keeps the snapshots next to the table cells so that
        delta calculations can use raw numeric values instead of
        reverse-parsing formatted strings.

        :param stage_label: Label shown in the first column
        :param before_snapshot: Server process snapshot taken before the stage
        :param after_snapshot: Server process snapshot taken after the stage
        :return: A dict with the following keys:
            "display"  Table cells
            "before"   Snapshot before the stage
            "after"    Snapshot after the stage
        """
        display: Dict[str, str] = ResourceReporter._server_display(stage_label, before_snapshot, after_snapshot)
        row: ServerResourceRow = {
            "display": display,
            "before": before_snapshot,
            "after": after_snapshot,
        }
        self._resource_rows.append(row)
        return row

    def add_client_row(self, stage_label: str, before_snapshot: Dict[str, Any], peak_snapshot: Optional[Dict[str, Any]],
                       settled_snapshot: Dict[str, Any]) -> ClientResourceRow:
        """
        Build and store a client resource row from before/peak/settled.

        The row keeps the snapshots next to the table cells so that
        delta calculations and JSON export can use raw numeric values.

        :param stage_label: Label shown in the first column
        :param before_snapshot: Client process snapshot taken before the stage
        :param peak_snapshot: Client process snapshot at peak RSS during the stage, or None
        :param settled_snapshot: Client process snapshot taken after the stage settled
        :return: A dict with the following keys:
            "display"  Table cells
            "before"   Snapshot before the stage
            "peak"     Peak snapshot, {} when None
            "settled"  Snapshot after the stage
        """
        before_rss_megabytes: float = before_snapshot.get("rss_megabytes")
        settled_rss_megabytes: float = settled_snapshot.get("rss_megabytes")
        rss_delta_megabytes: float = settled_rss_megabytes - before_rss_megabytes
        # Memory cells: megabytes with 1 decimal place, e.g. 123.5 MB.
        peak_rss_text: str = "-"
        if peak_snapshot:
            peak_rss_megabytes: float = peak_snapshot.get("rss_megabytes")
            peak_rss_text = f"{peak_rss_megabytes:.1f} MB"
        settled_cpu_percent: float = settled_snapshot.get("cpu_percent")
        settled_fds: Optional[int] = settled_snapshot.get("fds")
        settled_threads: Optional[int] = settled_snapshot.get("threads")
        display: Dict[str, str] = {
            "stage": str(stage_label),
            "before_rss": f"{before_rss_megabytes:.1f} MB",
            "peak_rss": peak_rss_text,
            "settled_rss": f"{settled_rss_megabytes:.1f} MB",
            "rss_delta": f"{rss_delta_megabytes:+.1f} MB",
            "cpu": f"{settled_cpu_percent:.1f}%",
            "fds": str(settled_fds),
            "threads": str(settled_threads),
        }
        row: ClientResourceRow = {
            "display": display,
            "before": before_snapshot,
            "peak": peak_snapshot or {},
            "settled": settled_snapshot,
        }
        self._client_rows.append(row)
        return row

    # Metric columns after "Component" in the combined table.
    METRIC_COLUMN_COUNT: int = 11

    def log_combined_analysis(self, total_client_requests: int, total_server_calls: int) -> None:
        """
        Log one combined server-app + client-app resource table.

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
        rows: List[List[str]] = self._combined_server_rows() + self._combined_client_rows()
        self.logger.info("\n%s", Formatters.SEPARATOR_LINE)
        if total_server_calls > 0:
            self.logger.info(
                "  RESOURCE ANALYSIS (%s client requests, %s server calls)",
                total_client_requests, total_server_calls,
            )
        else:
            self.logger.info("  RESOURCE ANALYSIS (%s total requests)", total_client_requests)
        self.logger.info("%s", Formatters.SEPARATOR_LINE)
        table_formatter: TableFormatter = TableFormatter()
        table_formatter.log_table(header, rows)
        self._log_resource_deltas()
        self._log_client_deltas()

    def _combined_server_rows(self) -> List[List[str]]:
        """
        Server-app rows for the combined table (na when absent).

        :return: One row per stage, or one row of na when there is no server data
        """
        if not self._resource_rows:
            return [ResourceReporter._na_row("Server app")]
        rows: List[List[str]] = []
        row: ServerResourceRow
        # One table row per server stage.
        for row in self._resource_rows:
            display: Dict[str, str] = row.get("display")
            # Server rows have no peak RSS.
            table_row: List[str] = [
                "Server app",
                display.get("stage"),
                display.get("before_rss"),
                "na",
                display.get("after_rss"),
                display.get("rss_delta"),
                display.get("cpu"),
                display.get("fds"),
                display.get("threads"),
                display.get("thread_delta"),
                display.get("connections"),
                display.get("children"),
            ]
            rows.append(table_row)
        return rows

    def _combined_client_rows(self) -> List[List[str]]:
        """
        Client-app rows for the combined table (na when absent).

        :return: One row per stage, or one row of na when there is no client data
        """
        if not self._client_rows:
            return [ResourceReporter._na_row("Client app")]
        rows: List[List[str]] = []
        row: ClientResourceRow
        # One table row per client stage.
        for row in self._client_rows:
            display: Dict[str, str] = row.get("display")
            # Client rows have no thread delta, connections or children.
            table_row: List[str] = [
                "Client app",
                display.get("stage"),
                display.get("before_rss"),
                display.get("peak_rss"),
                display.get("settled_rss"),
                display.get("rss_delta"),
                display.get("cpu"),
                display.get("fds"),
                display.get("threads"),
                "na",
                "na",
                "na",
            ]
            rows.append(table_row)
        return rows

    @staticmethod
    def _server_display(stage_label: str, before_snapshot: Dict[str, Any],
                        after_snapshot: Dict[str, Any]) -> Dict[str, str]:
        """
        Build the table cells of one server resource row.

        :param stage_label: Label shown in the first column
        :param before_snapshot: Server process snapshot taken before the stage
        :param after_snapshot: Server process snapshot taken after the stage
        :return: Cells by name: "stage", "before_rss", "after_rss", "rss_delta", "fds", "threads", "thread_delta",
            "connections", "cpu" and "children"
        """
        before_rss_megabytes: float = before_snapshot.get("rss_megabytes")
        after_rss_megabytes: float = after_snapshot.get("rss_megabytes")
        before_threads: int = before_snapshot.get("threads")
        after_threads: int = after_snapshot.get("threads")
        after_cpu_percent: float = after_snapshot.get("cpu_percent")
        rss_delta_megabytes: float = after_rss_megabytes - before_rss_megabytes
        thread_delta: int = after_threads - before_threads
        after_fds: Optional[int] = after_snapshot.get("fds")
        after_connections: Optional[int] = after_snapshot.get("connections")
        after_children: Optional[int] = after_snapshot.get("children")
        display: Dict[str, str] = {
            "stage": str(stage_label),
            "before_rss": f"{before_rss_megabytes:.1f} MB",
            "after_rss": f"{after_rss_megabytes:.1f} MB",
            "rss_delta": f"{rss_delta_megabytes:+.1f} MB",
            "fds": str(after_fds),
            "threads": f"{before_threads} -> {after_threads}",
            "thread_delta": f"{thread_delta:+d}",
            "connections": str(after_connections),
            "cpu": f"{after_cpu_percent:.1f}%",
            "children": str(after_children),
        }
        return display

    @staticmethod
    def _na_row(component: str) -> List[str]:
        """
        Build a combined-table row for a component with no data.

        :param component: Component name for the first column
        :return: The component name, then "na" for each metric column
        """
        row: List[str] = [component]
        unused_index: int
        # One "na" cell per metric column.
        for unused_index in range(ResourceReporter.METRIC_COLUMN_COUNT):
            row.append("na")
        return row

    def _log_resource_deltas(self) -> None:
        """
        Log overall resource deltas if enough data points.
        """
        if len(self._resource_rows) < 2:
            return
        first_row: ServerResourceRow = self._resource_rows[0]
        last_row: ServerResourceRow = self._resource_rows[-1]
        first_before_snapshot: Dict[str, Any] = first_row.get("before")
        last_after_snapshot: Dict[str, Any] = last_row.get("after")
        self._log_snapshot_deltas(
            "Server", first_before_snapshot, last_after_snapshot,
            fields=[
                ["RSS", "rss_megabytes", "%.1f MB"],
                ["FDs", "fds", "%s"],
                ["Threads", "threads", "%s"],
                ["Connections", "connections", "%s"],
                ["Children", "children", "%s"],
            ],
        )

    def _log_client_deltas(self) -> None:
        """
        Log overall client resource deltas if enough data points.
        """
        if len(self._client_rows) < 2:
            return
        first_row: ClientResourceRow = self._client_rows[0]
        last_row: ClientResourceRow = self._client_rows[-1]
        first_before_snapshot: Dict[str, Any] = first_row.get("before")
        last_settled_snapshot: Dict[str, Any] = last_row.get("settled")
        self._log_snapshot_deltas(
            "Client", first_before_snapshot, last_settled_snapshot,
            fields=[
                ["RSS", "rss_megabytes", "%.1f MB"],
                ["FDs", "fds", "%s"],
                ["Threads", "threads", "%s"],
            ],
        )

    def _log_snapshot_deltas(self, label: str, before_snapshot: Dict[str, Any], after_snapshot: Dict[str, Any],
                             fields: List[List[str]]) -> None:
        """
        Log deltas between two ResourceSnapshots.

        :param label: Component name shown in the heading
        :param before_snapshot: Snapshot from the first stage
        :param after_snapshot: Snapshot from the last stage
        :param fields: [display name, snapshot key, % format] of each field to log
        """
        maximum_name_length: int = 0
        name: str
        key: str
        format_pattern: str
        # Find the longest display name.
        for name, key, format_pattern in fields:
            name_length: int = len(name)
            maximum_name_length = max(maximum_name_length, name_length)
        self.logger.info("\n  %s overall deltas (first stage vs last stage):", label)
        # One delta line per field.
        for name, key, format_pattern in fields:
            delta: float = after_snapshot.get(key) - before_snapshot.get(key)
            padded: str = f"{name}:".ljust(maximum_name_length + 1)
            formatted: str = format_pattern % abs(delta)
            sign: str = "-"
            if delta >= 0:
                sign = "+"
            self.logger.info("    %s %s%s", padded, sign, formatted)
