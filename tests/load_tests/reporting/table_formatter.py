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
from typing import List
from typing import Sequence


class TableFormatter:
    """
    Formats and logs aligned console tables.
    """

    # The space between two columns, in the header, the rule and each row.
    COLUMN_GAP: str = "  "

    def __init__(self) -> None:
        """
        Constructor.
        """
        self.logger: Logger = getLogger(self.__class__.__name__)

    def log_table(self, header: List[str], rows: Sequence[Sequence[Any]]) -> None:
        """
        Log an aligned table given a header list and rows.

        :param header: Column names
        :param rows: Rows of cell values, one per column
        """
        column_widths: List[int] = []
        column_header: str
        # Start each column at the width of its header.
        for column_header in header:
            column_widths.append(len(column_header))
        row: Sequence[Any]
        index: int
        value: Any
        # Widen each column to its longest value.
        for row in rows:
            # Widen a column when this value is longer.
            for index, value in enumerate(row):
                column_widths[index] = max(column_widths[index], len(str(value)))
        column_patterns: List[str] = []
        column_width: int
        # One right-aligned field per column.
        for column_width in column_widths:
            column_patterns.append(f"{{:>{column_width}}}")
        format_pattern: str = TableFormatter.COLUMN_GAP.join(column_patterns)
        self.logger.info("%s", format_pattern.format(*header))
        # The rule is as wide as the header row: the column widths plus one COLUMN_GAP between columns.
        # The width depends on the rows, so it is computed here and not kept as a constant line.
        gap_width: int = len(TableFormatter.COLUMN_GAP)
        rule_width: int = sum(column_widths) + gap_width * (len(header) - 1)
        rule_line: str = "".ljust(rule_width, "-")
        self.logger.info("%s", rule_line)
        # One line per row.
        for row in rows:
            self.logger.info("%s", format_pattern.format(*row))
