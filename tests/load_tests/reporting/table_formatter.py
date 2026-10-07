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

"""Formats and logs aligned console tables."""

import logging
from typing import Any
from typing import List
from typing import Sequence

logger: logging.Logger = logging.getLogger(__name__)


class TableFormatter:
    """Formats and logs aligned tables."""

    @staticmethod
    def log_table(header: List[str], rows: Sequence[Sequence[Any]]) -> None:
        """
        Log an aligned table given a header list and rows.

        :param header: Column names
        :param rows: Rows of cell values, one per column
        """
        column_widths: List[int] = [len(column_header) for column_header in header]
        for row in rows:
            for index, value in enumerate(row):
                column_widths[index] = max(column_widths[index], len(str(value)))
        format_pattern: str = "  ".join(f"{{:>{column_width}}}" for column_width in column_widths)
        logger.info("%s", format_pattern.format(*header))
        logger.info("%s", "-" * (sum(column_widths) + 2 * (len(header) - 1)))
        for row in rows:
            logger.info("%s", format_pattern.format(*row))
