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

"""Validates and resolves user input for load test configuration.

Handles stage resolution, max-request capping, and the interactive
cost-confirmation flow that fires a single probe request to measure
actual token usage before committing to a full run.
"""

import logging
import os
import sys
from argparse import Namespace
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

import psutil

from tests.load_tests.config import DEFAULT_STAGES
from tests.load_tests.config import LEVEL_ADV
from tests.load_tests.config import SEPARATOR_WIDTH
from tests.load_tests.confirm import Confirm
from tests.load_tests.project_paths import ProjectPaths
from tests.load_tests.reporting.system_resources import SystemResources
from tests.load_tests.traffic.runner import TrafficRunner

logger: logging.Logger = logging.getLogger(__name__)


class InputValidator:
    """Validates and resolves user input for load test configuration.

    Holds the parsed CLI args so that callers do not need to pass
    them to every method.
    """

    def __init__(self, args: Namespace) -> None:
        """
        Constructor.

        :param args: Parsed command-line arguments
        """
        self._args: Namespace = args

    def validate_agent_name(self) -> None:
        """Reject --agent values that look like filesystem paths.

        The server resolves agents by registry-relative name
        (e.g. 'basic/hello_world'), not by absolute path.
        """
        agent: str = self._args.agent
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

    def validate_fixtures_hocon_dir(self) -> List[str]:
        """Resolve --fixtures-hocon-dir into a sorted list of *.hocon files.

        Returns an empty list when the flag was not given, meaning
        prompts come from the JSON profile as before. When given, the
        hocon files take precedence over the profile's prompts; the
        profile is still used for the remaining settings.

        The flag names the parent fixtures directory (default
        tests/fixtures/load_tests); the agent subfolder is derived
        from --agent the same way AgentProfileFactory derives the JSON
        filename: basic/hello_world -> hello_world.

        :return: Sorted *.hocon paths in the agent's fixtures folder; empty when --fixtures-hocon-dir is not given
        """
        parent_dir: Optional[str] = self._args.fixtures_hocon_dir
        if not parent_dir:
            return []

        if not os.path.isabs(parent_dir):
            project_root: Optional[str] = ProjectPaths.resolve_project_root(self._args.project_root)
            parent_dir = os.path.join(project_root or os.getcwd(), parent_dir)

        agent_base_name: str = ProjectPaths.agent_base_name(self._args.agent)
        hocon_dir: str = os.path.join(parent_dir, agent_base_name)

        if not os.path.isdir(hocon_dir):
            logger.error(
                "ERROR: no hocon fixtures directory for agent '%s':\n"
                "  Expected: %s\n"
                "  Check --fixtures-hocon-dir / --project-root.",
                self._args.agent, hocon_dir,
            )
            sys.exit(1)

        hocon_files: List[str] = sorted(
            os.path.join(hocon_dir, file_name)
            for file_name in os.listdir(hocon_dir)
            if file_name.endswith(".hocon")
            and os.path.isfile(os.path.join(hocon_dir, file_name))
        )
        if not hocon_files:
            logger.error("ERROR: no *.hocon files found in:\n  %s", hocon_dir)
            sys.exit(1)

        return hocon_files

    def resolve_stages(self) -> List[int]:
        """Return the list of concurrency stages to run.

        If --ramp is set and --stages provided, parse the CSV.
        If --ramp is set without --stages, use DEFAULT_STAGES.
        Otherwise return a single-stage list from --num-requests.

        :return: Requests per stage
        """
        if self._args.ramp:
            if self._args.stages is not None:
                stages: List[int] = []
                try:
                    stages = [
                        int(stage_text.strip())
                        for stage_text in self._args.stages.split(",")
                        if stage_text.strip()
                    ]
                except ValueError:
                    logger.error(
                        "--stages must be comma-separated integers (e.g. 3,10,30). Got: '%s'",
                        self._args.stages,
                    )
                    sys.exit(1)
                if not stages or any(stage <= 0 for stage in stages):
                    logger.error("--stages values must be positive integers. Got: '%s'", self._args.stages)
                    sys.exit(1)
                return stages
            return list(DEFAULT_STAGES)
        if self._args.num_requests <= 0:
            logger.error("--num-requests must be a positive integer. Got: %s", self._args.num_requests)
            sys.exit(1)
        return [self._args.num_requests]

    def resolve_max_requests(self, stages: List[int]) -> int:
        """
        Return the effective max-requests cap.

        :param stages: Requests per stage
        :return: --max-requests when given, else sum(stages) * --num-rounds
        """
        if self._args.num_rounds <= 0:
            logger.error("--num-rounds must be a positive integer. Got: %s", self._args.num_rounds)
            sys.exit(1)
        if self._args.max_requests is not None:
            if self._args.max_requests <= 0:
                logger.error("--max-requests must be a positive integer. Got: %s", self._args.max_requests)
                sys.exit(1)
            return self._args.max_requests
        return sum(stages) * self._args.num_rounds

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def confirm_cost(self, stages: List[int], total_cap_requests: int, runner: TrafficRunner,
                     output_dir: Optional[str] = None, stale_log_age: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Display PRE-RUN SUMMARY and optionally run a dry-run probe.

        The dry-run probe + cost confirmation runs by default at min
        and norm levels; --no-dry-run bypasses it. At adv level it does
        not run by default (adv is an explicit stress test).

        When skipped, shows the summary and returns immediately.
        Otherwise fires one probe request with --tokens to measure
        actual token usage, collects warnings, and asks the user to
        confirm.

        Returns the probe result dict if a probe was run, else None.

        :param stages: Requests per stage
        :param total_cap_requests: Most requests to send, from resolve_max_requests
        :param runner: Traffic runner used to fire the probe request
        :param output_dir: Directory for the probe's output files, or None
        :param stale_log_age: Minutes since the server log was last modified when it looks stale, or None
        :return: The probe result, or None when no probe was run
        """
        total_planned_requests: int = sum(stages) * self._args.num_rounds
        capped_requests: int = min(total_planned_requests, total_cap_requests)

        self._print_summary_header(stages, total_planned_requests, capped_requests)

        warnings: List[str] = []
        if self._args.no_dry_run or self._args.level == LEVEL_ADV:
            warnings = self._collect_warnings(capped_requests=capped_requests,
                                              total_planned_requests=total_planned_requests,
                                              stale_log_age_minutes=stale_log_age)
            self._print_warnings(warnings)
            logger.info("=" * SEPARATOR_WIDTH)
            return None

        probe_result: Dict[str, Any] = {}
        probe_measurements: Dict[str, Any] = {}
        probe_result, probe_measurements = self._run_cost_probe(runner, output_dir)

        remaining_requests: int = max(capped_requests - 1, 0)
        estimated_stage_duration_seconds: float = self._estimate_stage_duration(probe_measurements.get("elapsed", 0),
                                                                                remaining_requests)
        logger.info(
            "  Estimated stage duration: ~%ss (%.1fs x %s requests)",
            int(estimated_stage_duration_seconds),
            probe_measurements.get("elapsed", 0),
            remaining_requests,
        )

        warnings = self._collect_warnings(
            capped_requests=capped_requests,
            total_planned_requests=total_planned_requests,
            stale_log_age_minutes=stale_log_age,
            estimated_stage_duration_seconds=estimated_stage_duration_seconds,
            probe_tokens=probe_measurements.get("tokens", 0),
            probe_cost_dollars=probe_measurements.get("cost", 0.0),
            probe_model=probe_measurements.get("model", "unknown"),
        )
        self._print_warnings(warnings)

        logger.info(
            "\n  Tip: use --no-dry-run to skip this confirmation.\n"
            "       --no-dry-run does not auto-adjust timeouts.",
        )

        logger.info("=" * SEPARATOR_WIDTH)

        if not Confirm.ask(f"\nProceed with remaining {capped_requests - 1} requests?"):
            logger.info("Aborted by user.")
            sys.exit(0)

        return probe_result

    def _print_summary_header(self, stages: List[int], total_planned_requests: int, capped_requests: int) -> None:
        """
        Print the PRE-RUN SUMMARY header block.

        :param stages: Requests per stage, shown with --ramp
        :param total_planned_requests: Planned requests: sum(stages) * --num-rounds
        :param capped_requests: Requests after the --max-requests cap
        """
        args: Namespace = self._args
        logger.info("\n%s", "=" * SEPARATOR_WIDTH)
        logger.info("  PRE-RUN SUMMARY")
        logger.info("=" * SEPARATOR_WIDTH)
        logger.info("  Agent:    %s", args.agent)
        logger.info("  Level:    %s", args.level)
        if args.ramp:
            logger.info("  Stages:   %s", stages)
        logger.info(
            "  Requests: %s x %s round%s = %s total",
            args.num_requests,
            args.num_rounds,
            "s" if args.num_rounds > 1 else "",
            total_planned_requests,
        )
        if capped_requests < total_planned_requests:
            logger.info("  Capped:   %s (--max-requests)", capped_requests)
        logger.info("  Workers:  %s (concurrent)", args.max_workers)
        logger.info(
            "  Timeouts: --request-timeout %ss (%sm) / --idle-timeout %ss (%sm) / --stage-timeout %ss (%sm)",
            args.request_timeout, args.request_timeout // 60,
            args.idle_timeout, args.idle_timeout // 60,
            args.stage_timeout, args.stage_timeout // 60,
        )
        if args.total_timeout > 0:
            logger.info(
                "            --total-timeout %ss (%sm)",
                args.total_timeout, args.total_timeout // 60,
            )
        else:
            logger.info("            --total-timeout disabled")
        SystemResources.log_prerun()

    @staticmethod
    def _estimate_stage_duration(probe_elapsed_seconds: float, remaining_requests: int) -> float:
        """Estimate stage wall time from probe duration.

        LLM is the bottleneck, so concurrent requests do not
        scale linearly.  Estimate as probe_time x remaining
        requests (the probe already ran, so it is excluded).

        :param probe_elapsed_seconds: Seconds the probe request took
        :param remaining_requests: Requests still to send after the probe
        :return: Estimated stage seconds: probe_elapsed_seconds * remaining_requests
        """
        return probe_elapsed_seconds * remaining_requests

    def _collect_warnings(self, capped_requests: int, total_planned_requests: int,
                          stale_log_age_minutes: Optional[int] = None,
                          estimated_stage_duration_seconds: Optional[float] = None, probe_tokens: Optional[int] = None,
                          probe_cost_dollars: Optional[float] = None, probe_model: Optional[str] = None) -> List[str]:
        """
        Collect all pre-run warnings as a list of strings.

        :param capped_requests: Requests after the --max-requests cap
        :param total_planned_requests: Planned requests before the cap
        :param stale_log_age_minutes: Minutes since the server log was last modified when it looks stale, or None
        :param estimated_stage_duration_seconds: Estimated stage seconds, or None when no probe ran
        :param probe_tokens: Tokens the probe used, or None
        :param probe_cost_dollars: Probe cost in USD, or None
        :param probe_model: Model the probe used, or None
        :return: Warning texts; empty when there is nothing to warn about
        """
        warnings: List[str] = []

        if probe_cost_dollars is not None and probe_tokens:
            estimated_total_cost_dollars: float = probe_cost_dollars * capped_requests
            estimated_total_tokens: int = probe_tokens * capped_requests
            if estimated_total_cost_dollars > 1.0:
                warnings.append(
                    f"Estimated cost exceeds $1:\n"
                    f"     Probe used ~{probe_tokens:,} tokens (${probe_cost_dollars:.2f}) "
                    f"x {capped_requests} requests = "
                    f"~{estimated_total_tokens:,} tokens (~${estimated_total_cost_dollars:.2f})\n"
                    f"     Model: {probe_model}"
                )

        max_workers: int = self._args.max_workers
        num_requests: int = self._args.num_requests
        if not self._args.ramp and max_workers < num_requests:
            warnings.append(f"--max-workers ({max_workers}) < --num-requests ({num_requests}): requests run in batches")

        if (estimated_stage_duration_seconds is not None
                and estimated_stage_duration_seconds > self._args.stage_timeout):
            stage_timeout_seconds: int = self._args.stage_timeout
            warnings.append(
                f"Estimated stage duration ~{int(estimated_stage_duration_seconds)}s exceeds "
                f"--stage-timeout ({stage_timeout_seconds}s).\n"
                f"     Requests may be killed before completing."
            )

        if capped_requests < total_planned_requests:
            warnings.append(f"--max-requests ({capped_requests}) caps planned total ({total_planned_requests})")

        if stale_log_age_minutes is not None:
            warnings.append(f"Server log appears stale (last modified {stale_log_age_minutes}m ago)")

        warnings.extend(self._token_reporting_warnings())

        memory_warning: Optional[str] = self._check_memory_headroom(capped_requests)
        if memory_warning:
            warnings.append(memory_warning)

        return warnings

    def _token_reporting_warnings(self) -> List[str]:
        """Warn when the chat filter will suppress token reporting.

        Client-side LLM/token numbers arrive as a token-accounting
        message in the chat stream, which the server's MINIMAL filter
        drops.  Without a server log to fall back on, the run then
        reports no LLM or token usage at all.

        :return: One warning when --minimal is used with token accounting, else empty
        """
        args: Namespace = self._args
        if args.chat_filter != "minimal":
            return []
        if not args.include_tokens:
            return []
        if args.client_only or args.no_server_log:
            return [
                "--minimal drops the token-accounting message, and this run has no server log to fall back on:\n"
                "     no LLM or token usage will be reported.\n"
                "     Omit --minimal to report them."
            ]
        return [
            "--minimal drops the token-accounting message:\n"
            "     client-side LLM/token numbers will be unavailable (server-log values still apply).\n"
            "     Omit --minimal to report both."
        ]

    @staticmethod
    def _check_memory_headroom(num_requests: int) -> Optional[str]:
        """Warn if available memory looks insufficient.

        Uses a conservative per-request estimate based on
        typical server thread overhead.

        :param num_requests: Requests that may run at once
        :return: Warning text, or None when available memory looks sufficient
        """
        virtual_memory_stats: Any = psutil.virtual_memory()
        available_gigabytes: float = virtual_memory_stats.available / (1024 ** 3)
        per_request_megabytes: int = 2
        needed_gigabytes: float = (num_requests * per_request_megabytes) / 1024
        if needed_gigabytes > available_gigabytes * 0.8:
            return (
                f"Memory may be insufficient for {num_requests} concurrent requests:\n"
                f"     Estimated need: ~{needed_gigabytes:.1f}G "
                f"({num_requests} x ~{per_request_megabytes}MB per request)\n"
                f"     Available: {available_gigabytes:.1f}G / {virtual_memory_stats.total / (1024 ** 3):.1f}G total\n"
                f"     Consider fewer concurrent workers or a larger instance"
            )
        return None

    @staticmethod
    def _print_warnings(warnings: List[str]) -> None:
        """
        Print numbered warnings or 'No warnings'.

        :param warnings: Warning texts from _collect_warnings
        """
        if not warnings:
            logger.info("\n  No warnings.")
            return

        logger.warning("\n  WARNINGS (%s found):", len(warnings))
        for warning_number, warning in enumerate(warnings, 1):
            lines: List[str] = warning.split("\n")
            logger.warning("  %s. %s", warning_number, lines[0])
            for line in lines[1:]:
                logger.warning("  %s", line)

    def _run_cost_probe(self, runner: TrafficRunner,
                        output_dir: Optional[str]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Fire one probe request and return results.

        Fires a single request (tokens are enabled by default)
        and logs the outcome.

        Returns (probe_result, probe_data_dict).

        :param runner: Traffic runner used to fire the probe request
        :param output_dir: Directory for the probe's output files, or None
        :return: (probe_result, probe_measurements), where probe_measurements holds tokens, cost, model and elapsed
        """
        logger.info("\n  Running 1 dry-run probe to measure actual cost...")

        probe_result: Dict[str, Any] = runner.run_one_http(request_id=0, global_request_id=0, output_dir=output_dir)

        probe_tokens: int = probe_result.get("total_tokens", 0)
        probe_cost_dollars: float = probe_result.get("cost_usd", 0.0)
        probe_model: str = probe_result.get("model", "unknown")
        probe_status: str = probe_result.get("status", "FAILED")
        probe_elapsed_seconds: float = probe_result.get("elapsed", 0)

        logger.info("\n  Probe request completed in %.1fs (%s)", probe_elapsed_seconds, probe_status)

        if probe_tokens > 0:
            logger.info("  Probe tokens: %s (model: %s, cost: $%.4f)", f"{probe_tokens:,}", probe_model,
                        probe_cost_dollars)
        else:
            logger.info("  No token data from probe (agent may not track tokens).")

        probe_measurements: Dict[str, Any] = {
            "tokens": probe_tokens,
            "cost": probe_cost_dollars,
            "model": probe_model,
            "elapsed": probe_elapsed_seconds,
        }
        return probe_result, probe_measurements
