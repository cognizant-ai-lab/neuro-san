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

"""Aggregates and logs client disconnection analysis."""

import logging

logger = logging.getLogger(__name__)

SEPARATOR_WIDTH = 60


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
