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

"""Input validation — cost confirmation, stage resolution, and request caps."""

import logging
import sys
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from tests.load_tests.config import DEFAULT_STAGES
from tests.load_tests.traffic.runner import TrafficRunner

logger = logging.getLogger(__name__)


class InputValidator:
    """Validates and resolves user input for load test configuration."""

    @staticmethod
    def resolve_stages(args) -> List[int]:
        """Return the list of concurrency stages to run.

        In ramp mode, returns parsed --stages or defaults.
        In flat mode, returns a single-element list from --num-requests.
        """
        if args.ramp:
            if args.stages is not None:
                return [
                    int(s.strip()) for s in args.stages.split(",")
                ]
            return list(DEFAULT_STAGES)
        return [args.num_requests]

    @staticmethod
    def resolve_max_requests(args, stages) -> int:
        """Return the effective max-requests cap."""
        if args.max_requests is not None:
            return args.max_requests
        if args.ramp:
            return sum(stages) * args.num_rounds
        return 100

    @staticmethod
    def confirm_cost(
            args, stages, total_cap, profile=None,
            output_dir=None,
    ) -> Optional[Dict[str, Any]]:
        """Display cost warning and optionally run a dry-run probe.

        With --yes: shows the cost warning and returns immediately.
        Without --yes: fires one probe request with --tokens to
        measure actual token usage, shows the extrapolated cost,
        and asks the user to confirm.

        Returns the probe result dict if a probe was run, else None.
        """
        total_planned = sum(stages) * args.num_rounds
        capped = min(total_planned, total_cap)
        logger.info("\n%s", "=" * 60)
        logger.info("  COST WARNING: REAL LLM CALLS")
        logger.info("=" * 60)
        if args.ramp:
            logger.info("  Ramp-up stages: %s", stages)
            logger.info("  Rounds: %s", args.num_rounds)
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

        logger.info("=" * 60)

        if args.yes:
            return None

        return InputValidator._run_cost_probe(
            args, profile, capped, output_dir,
        )

    @staticmethod
    def _run_cost_probe(
            args, profile, total_requests, output_dir,
    ) -> Optional[Dict[str, Any]]:
        """Fire one probe request with --tokens and confirm cost."""
        logger.info(
            "\nRunning 1 dry-run probe to measure actual cost...",
        )

        # Temporarily enable token parsing for the probe
        original_include = args.include_tokens
        args.include_tokens = True
        probe_result = TrafficRunner.run_one(
            args, profile,
            request_id=1, global_request_id=0,
            output_dir=output_dir,
        )
        args.include_tokens = original_include

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
