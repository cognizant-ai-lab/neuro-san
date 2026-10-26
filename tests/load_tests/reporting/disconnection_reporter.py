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

import logging
from typing import Any
from typing import Dict
from typing import List

from tests.load_tests.reporting.formatters import Formatters

logger: logging.Logger = logging.getLogger(__name__)


class DisconnectionReporter:
    """
    Aggregates and logs client disconnection analysis.

    Holds the collected stage summaries for analysis.
    """

    def __init__(self, stage_summaries: List[Dict[str, Any]]) -> None:
        """
        Constructor.

        :param stage_summaries: Per-stage summaries collected during the run
        """
        self._summaries: List[Dict[str, Any]] = stage_summaries

    def log_disconnection_summary(self) -> None:
        """
        Log aggregate client disconnection report.
        """
        all_disconnections: List[Dict[str, Any]] = []
        index: int
        stage: Dict[str, Any]
        disconnection: Dict[str, Any]
        # Collect the disconnections of every stage.
        for index, stage in enumerate(self._summaries):
            # Copy each disconnection and add its batch number.
            for disconnection in stage.get("disconnections") or []:
                disconnection_copy: Dict[str, Any] = dict(disconnection)
                disconnection_copy.update({"batch": index + 1})
                all_disconnections.append(disconnection_copy)
        if not all_disconnections:
            return
        logger.info("\n%s", Formatters.SEPARATOR_LINE)
        logger.info("  CLIENT DISCONNECTIONS (%s detected in server log)", len(all_disconnections))
        logger.info("%s", Formatters.SEPARATOR_LINE)
        # One log line per disconnection.
        for disconnection in all_disconnections:
            logger.info(
                "  Batch %s: %s — %s still processing at disconnect",
                disconnection.get("batch", "?"),
                disconnection.get("request_id", "unknown"),
                disconnection.get("agent", "unknown"),
            )
        logger.info(
            """
  These requests had their client disconnect
  before the server finished. The server detected the
  disconnection and cancelled in-flight tasks.
  If unexpected, consider increasing --idle-timeout.""",
        )
