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

from argparse import Namespace
from logging import Logger
from logging import getLogger
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from tests.load_tests.reporting.duration_parser import DurationParser
from tests.load_tests.reporting.formatters import Formatters
from tests.load_tests.reporting.table_formatter import TableFormatter


class LeakReporter:
    """
    Logs the overall results and the leak analysis of the mock LLM load test.

    The leak analysis is a per-round resource table for each server, then the deltas
    between round 1 before and the last round settled.
    """

    HEADER: List[str] = ["Round", "Before RSS", "Settled RSS", "RSS Delta",
                         "FDs", "Threads", "Thread Delta",
                         "Conns", "CPU%", "Children"]

    def __init__(self, args: Namespace) -> None:
        """
        Initialize the reporter.

        :param args: Parsed command-line arguments from MockLoadTestArguments.parse_args()
        """
        self.logger: Logger = getLogger(self.__class__.__name__)
        self._args: Namespace = args

    def log_results(self, rounds_result: Dict[str, Any]) -> None:
        """
        Log the overall results summary and leak analysis tables.

        :param rounds_result: Result of MockRoundRunner.run_rounds(): "totals" with "passed", "failed" and
                              "time_seconds", and "server_rows" and "mock_rows" from its _build_snapshot_row()
        """
        totals: Dict[str, float] = rounds_result.get("totals")
        server_rows: List[Dict[str, Any]] = rounds_result.get("server_rows")
        mock_rows: List[Dict[str, Any]] = rounds_result.get("mock_rows")
        total_requests: int = self._args.num_requests * self._args.num_rounds
        passed: int = totals.get("passed")
        failed: int = totals.get("failed")
        time_seconds: float = totals.get("time_seconds")

        self.logger.info("\n%s", Formatters.SEPARATOR_LINE)
        self.logger.info("  OVERALL RESULTS")
        self.logger.info("%s", Formatters.SEPARATOR_LINE)
        self.logger.info("  Total requests: %s (%s passed, %s failed)", total_requests, passed, failed)
        time_text: str = DurationParser.format_minutes_seconds(time_seconds)
        self.logger.info("  Total time:     %s", time_text)
        if total_requests > 0:
            average_request_seconds: float = time_seconds / total_requests
            average_request_text: str = DurationParser.format_minutes_seconds(average_request_seconds)
            self.logger.info("  Avg per request: %s", average_request_text)

        self.logger.info("\n%s", Formatters.SEPARATOR_LINE)
        self.logger.info("  LEAK ANALYSIS ACROSS %s ROUNDS (%s total requests)",
                         self._args.num_rounds, total_requests)
        self.logger.info("%s", Formatters.SEPARATOR_LINE)

        if server_rows:
            self.logger.info("\nNEURO-SAN SERVER:")
            LeakReporter._log_snapshot_table(server_rows)

        if mock_rows:
            self.logger.info("\nMOCK LLM SERVER:")
            LeakReporter._log_snapshot_table(mock_rows)

        if len(server_rows) >= 2:
            self._log_overall_deltas("Server", server_rows)

        if len(mock_rows) >= 2:
            self._log_overall_deltas("Mock", mock_rows)

    @staticmethod
    def _format_snapshot_row(snapshot_row: Dict[str, Any]) -> List[str]:
        """
        Format one row from MockRoundRunner._build_snapshot_row() as table cells.

        :param snapshot_row: Row from MockRoundRunner._build_snapshot_row()
        :return: Cell text in the column order of HEADER
        """
        round_number: int = snapshot_row.get("round_number")
        before_rss_megabytes: float = snapshot_row.get("before_rss_megabytes")
        settled_rss_megabytes: float = snapshot_row.get("settled_rss_megabytes")
        rss_delta_megabytes: float = snapshot_row.get("rss_delta_megabytes")
        fds: Optional[int] = snapshot_row.get("fds")
        before_threads: Optional[int] = snapshot_row.get("before_threads")
        settled_threads: Optional[int] = snapshot_row.get("settled_threads")
        thread_delta: int = snapshot_row.get("thread_delta")
        connections: Optional[int] = snapshot_row.get("connections")
        cpu_percent: float = snapshot_row.get("cpu_percent")
        children: Optional[int] = snapshot_row.get("children")
        cells: List[str] = [
            str(round_number),
            f"{before_rss_megabytes:.1f} MB",
            f"{settled_rss_megabytes:.1f} MB",
            f"+{rss_delta_megabytes:.1f} MB",
            str(fds),
            f"{before_threads} -> {settled_threads}",
            f"+{thread_delta}",
            str(connections),
            f"{cpu_percent:.1f}%",
            str(children),
        ]
        return cells

    @staticmethod
    def _log_snapshot_table(snapshot_rows: List[Dict[str, Any]]) -> None:
        """
        Log the per-round resource table.

        :param snapshot_rows: Rows from MockRoundRunner._build_snapshot_row(), one per round
        """
        table_rows: List[List[str]] = []
        snapshot_row: Dict[str, Any]
        # Format each round's row as table cells.
        for snapshot_row in snapshot_rows:
            cells: List[str] = LeakReporter._format_snapshot_row(snapshot_row)
            table_rows.append(cells)
        table_formatter: TableFormatter = TableFormatter()
        table_formatter.log_table(LeakReporter.HEADER, table_rows)

    def _log_overall_deltas(self, label: str, rows: List[Dict[str, Any]]) -> None:
        """
        Log overall resource deltas between the first and last rounds.

        :param label: Process name shown in the heading ("Server" or "Mock")
        :param rows: Rows from MockRoundRunner._build_snapshot_row(), one per round
        """
        first_row: Dict[str, Any] = rows[0]
        last_row: Dict[str, Any] = rows[-1]
        rss_delta_megabytes: float = last_row.get("settled_rss_megabytes") - first_row.get("before_rss_megabytes")
        fds_delta: int = last_row.get("fds") - first_row.get("fds")
        thread_delta: int = last_row.get("settled_threads") - first_row.get("before_threads")
        connections_delta: int = last_row.get("connections") - first_row.get("connections")
        children_delta: int = last_row.get("children") - first_row.get("children")
        self.logger.info("\n%s overall deltas (round 1 before vs round %s settled):", label,
                         self._args.num_rounds)
        self.logger.info("  RSS:         +%.1f MB", rss_delta_megabytes)
        self.logger.info("  FDs:         +%s", fds_delta)
        self.logger.info("  Threads:     +%s", thread_delta)
        self.logger.info("  Connections: +%s", connections_delta)
        self.logger.info("  Children:    +%s", children_delta)
