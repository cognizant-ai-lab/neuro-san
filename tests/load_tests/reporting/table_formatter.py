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

"""Formats and logs aligned console tables."""

import logging

logger = logging.getLogger(__name__)


class TableFormatter:
    """Formats and logs aligned tables."""

    @staticmethod
    def log_table(header, rows) -> None:
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
