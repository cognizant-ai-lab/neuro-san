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

"""Trend history — read the append-only history file and log a table.

Complements the cross-run comparison, which answers a different
question: that one groups runs by request count to show how the system
scales, while this one keeps runs in the order they happened so a
regression between neuro-san versions is visible.
"""

import json
import logging
import os

from typing import Dict
from typing import List
from typing import Optional

from tests.load_tests.config import HISTORY_FILE_NAME
from tests.load_tests.config import HISTORY_THRESHOLDS_SECONDS
from tests.load_tests.reporting.table_formatter import TableFormatter

logger = logging.getLogger(__name__)


class TrendHistory:
    """Reads history JSONL records and logs them in run order."""

    def __init__(self, path, *, agent_filter=None) -> None:
        self._path = path
        self._agent_filter: set = (
            set(agent_filter) if agent_filter else set()
        )

    def run(self) -> None:
        """Read the history file and log one row per recorded run."""
        history_path = self._resolve_path()
        if history_path is None:
            logger.info(
                "No history file found at %s. Runs append one record "
                "each, so this file appears after the first run.",
                self._path,
            )
            return
        records = self._read_records(history_path)
        if not records:
            logger.info("No usable records in %s", history_path)
            return
        if self._agent_filter:
            records = [
                record for record in records
                if record.get("agent") in self._agent_filter
            ]
            if not records:
                logger.info(
                    "No records for agent(s) %s in %s",
                    ", ".join(sorted(self._agent_filter)),
                    history_path,
                )
                return
        records.sort(key=lambda record: record.get("timestamp", ""))
        logger.info("")
        logger.info(
            "TREND HISTORY (%s, %s run(s))",
            history_path, len(records),
        )
        TableFormatter.log_table(
            self._header(), [self._row(record) for record in records],
        )
        logger.info("")

    def _resolve_path(self) -> Optional[str]:
        """Return the history file to read, or None when absent.

        Accepts either the file itself or a directory holding the
        default-named history file, so the path printed at the end of a
        run and its parent output directory both work.
        """
        if os.path.isfile(self._path):
            return self._path
        candidate = os.path.join(self._path, HISTORY_FILE_NAME)
        if os.path.isfile(candidate):
            return candidate
        return None

    @staticmethod
    def _read_records(history_path) -> List[Dict]:
        """Parse the JSONL file, skipping unreadable lines.

        A partially written final line is expected when a run is
        interrupted, so a bad line is reported and skipped rather than
        losing every earlier record.
        """
        records: List[Dict] = []
        skipped = 0
        try:
            with open(history_path, "r", encoding="utf-8") as handle:
                for line in handle:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        skipped += 1
                        continue
                    if isinstance(record, dict):
                        records.append(record)
                    else:
                        skipped += 1
        except OSError as exc:
            logger.warning(
                "Could not read history file %s: %s", history_path, exc,
            )
            return []
        if skipped:
            logger.warning(
                "  Skipped %s unreadable line(s) in %s",
                skipped, history_path,
            )
        return records

    @staticmethod
    def _header() -> List[str]:
        """Return the table header, including a column per threshold."""
        header = [
            "timestamp", "neuro-san", "agent", "mode", "via",
            "reqs", "done",
        ]
        header.extend(
            f"<{int(threshold)}s"
            for threshold in HISTORY_THRESHOLDS_SECONDS
        )
        header.extend(["ttfr", "avg", "wall", "err", "warn"])
        return header

    @staticmethod
    def _row(record) -> List[str]:
        """Format one history record as a table row.

        Client and server-only records count requests under different
        keys, and a server log cannot measure the client's time to
        first response, so the missing values render as "-".

        The transport is shown because subprocess and HTTP runs are not
        comparable to each other, and both land in the same file.
        """
        mode = record.get("mode", "client")
        requests = record.get(
            "total_requests", record.get("expected_requests", 0),
        )
        completed = record.get(
            "completed", record.get("received_requests", 0),
        )
        row = [
            TrendHistory._fmt_timestamp(record.get("timestamp", "")),
            record.get("neuro_san_version", "unknown"),
            record.get("agent", "unknown"),
            mode,
            record.get("transport", "-"),
            str(requests),
            str(completed),
        ]
        row.extend(
            str(record.get(f"completed_within_{int(threshold)}s", "-"))
            for threshold in HISTORY_THRESHOLDS_SECONDS
        )
        row.append(
            TrendHistory._fmt_seconds(
                record.get("avg_first_response_s"),
            ),
        )
        row.append(
            TrendHistory._fmt_seconds(record.get("avg_duration_s")),
        )
        row.append(
            TrendHistory._fmt_seconds(record.get("wall_time_s")),
        )
        row.append(str(record.get("server_error_count", "-")))
        row.append(str(record.get("tool_warning_count", "-")))
        return row

    @staticmethod
    def _fmt_timestamp(timestamp) -> str:
        """Shorten an ISO timestamp to "YYYY-MM-DD HH:MM"."""
        if not timestamp:
            return "-"
        text = str(timestamp).replace("T", " ")
        return text[:16]

    @staticmethod
    def _fmt_seconds(value) -> str:
        """Format a seconds value, rendering absent or zero as "-"."""
        if not isinstance(value, (int, float)) or value <= 0:
            return "-"
        return f"{value:.1f}s"
