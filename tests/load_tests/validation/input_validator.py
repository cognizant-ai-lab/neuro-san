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

"""Validates and resolves user input for load test configuration.

Handles stage resolution, max-request capping, and the interactive
cost-confirmation flow that fires a single probe request to measure
actual token usage before committing to a full run.
"""

import logging
import os
import sys
from typing import List
from typing import Optional

from tests.load_tests.config import DEFAULT_STAGES
from tests.load_tests.config import RequestResult
from tests.load_tests.config import SEPARATOR_WIDTH

logger = logging.getLogger(__name__)


class InputValidator:
    """Validates and resolves user input for load test configuration.

    Holds the parsed CLI args so that callers do not need to pass
    them to every method.
    """

    def __init__(self, args) -> None:
        self._args = args

    def validate_agent_name(self) -> None:
        """Reject --agent values that look like filesystem paths.

        The server resolves agents by registry-relative name
        (e.g. 'basic/hello_world'), not by absolute path.
        """
        agent = self._args.agent
        if os.path.isabs(agent):
            logger.error(
                "ERROR: --agent appears to be a filesystem path:\n"
                "  %s\n\n"
                "Use the registry-relative name instead.\n"
                "For example, if the agent HOCON is at:\n"
                "  registries/basic/hello_world.hocon\n"
                "Then use:\n"
                "  --agent basic/hello_world",
                agent,
            )
            sys.exit(1)

    def resolve_stages(self) -> List[int]:
        """Return the list of concurrency stages to run.

        If --ramp is set and --stages provided, parse the CSV.
        If --ramp is set without --stages, use DEFAULT_STAGES.
        Otherwise return a single-stage list from --num-requests.
        """
        if self._args.ramp:
            if self._args.stages is not None:
                return [
                    int(s.strip())
                    for s in self._args.stages.split(",")
                ]
            return list(DEFAULT_STAGES)
        return [self._args.num_requests]

    def resolve_max_requests(self, stages) -> int:
        """Return the effective max-requests cap."""
        if self._args.max_requests is not None:
            return self._args.max_requests
        if self._args.ramp:
            return sum(stages) * self._args.num_rounds
        return 100

    # pylint: disable=too-many-arguments
    def confirm_cost(
            self, stages, total_cap, *, runner,
            profile=None, output_dir=None,
    ) -> Optional[RequestResult]:
        """Display cost warning and optionally run a dry-run probe.

        With --yes: shows the cost warning and returns immediately.
        Without --yes: fires one probe request with --tokens to
        measure actual token usage, shows the extrapolated cost,
        and asks the user to confirm.

        Returns the probe result dict if a probe was run, else None.
        """
        total_planned = sum(stages) * self._args.num_rounds
        capped = min(total_planned, total_cap)
        logger.info("\n%s", "=" * SEPARATOR_WIDTH)
        logger.info("  COST WARNING: REAL LLM CALLS")
        logger.info("=" * SEPARATOR_WIDTH)
        if self._args.ramp:
            logger.info("  Ramp-up stages: %s", stages)
            logger.info("  Rounds: %s", self._args.num_rounds)
        logger.info("  Total planned requests: %s", total_planned)
        if capped < total_planned:
            logger.info(
                "  Capped by --max-requests: %s", capped,
            )

        if profile and profile.estimated_tokens_per_request:
            total_tokens = (
                capped * profile.estimated_tokens_per_request
            )
            logger.info(
                "  Estimated tokens: %s × %s = ~%s tokens",
                capped,
                f"{profile.estimated_tokens_per_request:,}",
                f"{total_tokens:,}",
            )
        else:
            logger.info(
                "  Each request involves multiple recursive "
                "LLM calls."
            )
            logger.info(
                "  Estimated cost depends on model and prompt "
                "complexity."
            )

        logger.info("=" * SEPARATOR_WIDTH)

        if self._args.yes:
            return None

        return self._run_cost_probe(runner, capped, output_dir)

    def _run_cost_probe(
            self, runner, total_requests, output_dir,
    ) -> Optional[RequestResult]:
        """Fire one probe request with --tokens and confirm cost.

        Temporarily enables token tracking, fires a single request,
        and extrapolates cost for the full run.  Exits if the user
        declines to proceed.
        """
        logger.info(
            "\nRunning 1 dry-run probe to measure actual cost...",
        )

        original_include = self._args.include_tokens
        self._args.include_tokens = True
        try:
            probe_result = runner.run_one(
                request_id=0, global_request_id=0,
                output_dir=output_dir,
            )
        finally:
            self._args.include_tokens = original_include

        probe_tokens = probe_result.get("total_tokens", 0)
        probe_cost = probe_result.get("cost_usd", 0.0)
        probe_model = probe_result.get("model", "unknown")
        probe_status = probe_result.get("status", "FAILED")
        probe_elapsed = probe_result.get("elapsed", 0)

        logger.info(
            "  Probe result: %s in %.1fs",
            probe_status, probe_elapsed,
        )
        logger.info(
            "  Probe tokens: %s (model: %s, cost: $%.6f)",
            f"{probe_tokens:,}", probe_model, probe_cost,
        )

        if probe_tokens > 0:
            est_total_cost = probe_cost * total_requests
            est_total_tokens = probe_tokens * total_requests
            logger.info(
                "  Estimated total for %s requests: "
                "~%s tokens (~$%.4f)",
                total_requests,
                f"{est_total_tokens:,}",
                est_total_cost,
            )
        else:
            logger.info(
                "  No token data from probe (agent may not "
                "track tokens)."
            )

        answer = input(
            "\nProceed with remaining "
            f"{total_requests - 1} requests? [y/N]: ",
        ).strip().lower()
        if answer not in ("y", "yes"):
            logger.info("Aborted by user.")
            sys.exit(0)

        return probe_result
