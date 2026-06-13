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
from typing import List

from tests.load_tests.config import DEFAULT_STAGES

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
    def confirm_cost(args, stages, total_cap, profile=None):
        """Display cost warning and ask for confirmation unless --yes."""
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

        if not args.yes:
            answer = input("\nProceed? [y/N]: ").strip().lower()
            if answer not in ("y", "yes"):
                logger.info("Aborted by user.")
                sys.exit(0)
