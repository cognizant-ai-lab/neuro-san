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
from os import getcwd
from os import listdir
from os.path import isabs
from os.path import isdir
from os.path import isfile
from os.path import join
from argparse import Namespace
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

from psutil import virtual_memory

from tests.load_tests.load_test_constants import LoadTestConstants
from tests.load_tests.confirm import Confirm
from tests.load_tests.monitoring.resource_monitor import ResourceMonitor
from tests.load_tests.project_paths import ProjectPaths
from tests.load_tests.reporting.formatters import Formatters
from tests.load_tests.reporting.system_resources import SystemResources
from tests.load_tests.traffic.runner import TrafficRunner
from tests.load_tests.validation.load_test_abort_error import LoadTestAbortError

logger: logging.Logger = logging.getLogger(__name__)


class InputValidator:
    """
    Validates and resolves user input for load test configuration.

    Handles stage resolution, max-request capping, and the interactive
    cost-confirmation flow that fires a single probe request to measure
    actual token usage before committing to a full run.

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
        """
        Reject --agent values that look like filesystem paths.

        The server resolves agents by registry-relative name
        (e.g. 'basic/hello_world'), not by absolute path.
        """
        agent: str = self._args.agent
        if isabs(agent):
            logger.error(
                """ERROR: --agent appears to be a filesystem path:
  %s

Use the registry-relative name instead.
For example, if the agent HOCON is at:
  registries/basic/hello_world.hocon
Then use:
  --agent basic/hello_world""",
                agent,
            )
            raise LoadTestAbortError(1)

    def validate_fixtures_hocon_dir(self) -> List[str]:
        """
        Resolve --fixtures-hocon-dir into a sorted list of *.hocon files.

        Returns an empty list when the flag was not given, meaning
        prompts come from the JSON profile. When given, the
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

        if not isabs(parent_dir):
            project_root: Optional[str] = ProjectPaths.resolve_project_root(self._args.project_root)
            parent_dir = join(project_root or getcwd(), parent_dir)

        agent_base_name: str = ProjectPaths.agent_base_name(self._args.agent)
        hocon_dir: str = join(parent_dir, agent_base_name)

        if not isdir(hocon_dir):
            logger.error(
                """ERROR: no hocon fixtures directory for agent '%s':
  Expected: %s
  Check --fixtures-hocon-dir / --project-root.""",
                self._args.agent, hocon_dir,
            )
            raise LoadTestAbortError(1)

        hocon_files: List[str] = []
        file_name: str
        # Keep the *.hocon files of the directory.
        for file_name in listdir(hocon_dir):
            file_path: str = join(hocon_dir, file_name)
            if file_name.endswith(".hocon") and isfile(file_path):
                hocon_files.append(file_path)
        hocon_files.sort()
        if not hocon_files:
            logger.error("ERROR: no *.hocon files found in:\n  %s", hocon_dir)
            raise LoadTestAbortError(1)

        return hocon_files

    def resolve_stages(self) -> List[int]:
        """
        Return the list of concurrency stages to run.

        If --ramp is set and --stages provided, parse the CSV.
        If --ramp is set without --stages, use LoadTestConstants.DEFAULT_STAGES.
        Otherwise return a single-stage list from --num-requests.

        :return: Requests per stage
        """
        if self._args.ramp:
            if self._args.stages is not None:
                stages: List[int] = []
                stage_text: str = ""
                try:
                    # Parse each non-empty comma-separated value.
                    for stage_text in self._args.stages.split(","):
                        if stage_text.strip():
                            stages.append(int(stage_text.strip()))
                except ValueError as value_error:
                    logger.error(
                        "--stages must be comma-separated integers (e.g. 3,10,30). Got: '%s'",
                        self._args.stages,
                    )
                    raise LoadTestAbortError(1) from value_error
                has_non_positive: bool = False
                stage: int
                # Look for a stage that is zero or negative.
                for stage in stages:
                    if stage <= 0:
                        has_non_positive = True
                        break
                if not stages or has_non_positive:
                    logger.error("--stages values must be positive integers. Got: '%s'", self._args.stages)
                    raise LoadTestAbortError(1)
                return stages
            return list(LoadTestConstants.DEFAULT_STAGES)
        if self._args.num_requests <= 0:
            logger.error("--num-requests must be a positive integer. Got: %s", self._args.num_requests)
            raise LoadTestAbortError(1)
        return [self._args.num_requests]

    def resolve_max_requests(self, stages: List[int]) -> int:
        """
        Return the effective max-requests cap.

        :param stages: Requests per stage
        :return: --max-requests when given, else sum(stages) * --num-rounds
        """
        if self._args.num_rounds <= 0:
            logger.error("--num-rounds must be a positive integer. Got: %s", self._args.num_rounds)
            raise LoadTestAbortError(1)
        if self._args.max_requests is not None:
            if self._args.max_requests <= 0:
                logger.error("--max-requests must be a positive integer. Got: %s", self._args.max_requests)
                raise LoadTestAbortError(1)
            return self._args.max_requests
        return sum(stages) * self._args.num_rounds

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def confirm_cost(self, stages: List[int], total_cap_requests: int, runner: TrafficRunner,
                     output_dir: Optional[str] = None,
                     stale_log_age_minutes: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """
        Display PRE-RUN SUMMARY and optionally run a dry-run probe.

        The dry-run probe + cost confirmation runs by default at min
        and norm levels; --no-dry-run bypasses it. At adv level it does
        not run by default (adv is an explicit stress test).

        When skipped, shows the summary and returns immediately.
        Otherwise fires one probe request with --tokens to measure
        actual token usage, collects warnings, and asks the user to
        confirm.

        :param stages: Requests per stage
        :param total_cap_requests: Most requests to send, from resolve_max_requests
        :param runner: Traffic runner used to fire the probe request
        :param output_dir: Directory for the probe's output files, or None
        :param stale_log_age_minutes: Minutes since the server log was last modified when it looks stale, or None
        :return: The probe result, or None when no probe was run
        """
        total_planned_requests: int = sum(stages) * self._args.num_rounds
        capped_requests: int = min(total_planned_requests, total_cap_requests)

        self._print_summary_header(stages, total_planned_requests, capped_requests)

        warnings: List[str] = []
        if self._args.no_dry_run or self._args.level == LoadTestConstants.LEVEL_ADV:
            warnings = self._collect_warnings(capped_requests=capped_requests,
                                              total_planned_requests=total_planned_requests,
                                              stale_log_age_minutes=stale_log_age_minutes)
            self._print_warnings(warnings)
            logger.info("%s", Formatters.SEPARATOR_LINE)
            return None

        probe_result: Dict[str, Any] = {}
        probe_measurements: Dict[str, Any] = {}
        probe_result, probe_measurements = self._run_cost_probe(runner, output_dir)

        remaining_requests: int = max(capped_requests - 1, 0)
        probe_elapsed_seconds: float = probe_measurements.get("elapsed_seconds", 0)
        estimated_stage_duration_seconds: float = self._estimate_stage_duration(probe_elapsed_seconds,
                                                                                remaining_requests)
        logger.info(
            "  Estimated stage duration: ~%ss (%.1fs x %s requests)",
            int(estimated_stage_duration_seconds),
            probe_elapsed_seconds,
            remaining_requests,
        )

        warnings = self._collect_warnings(
            capped_requests=capped_requests,
            total_planned_requests=total_planned_requests,
            stale_log_age_minutes=stale_log_age_minutes,
            estimated_stage_duration_seconds=estimated_stage_duration_seconds,
            probe_tokens=probe_measurements.get("tokens", 0),
            probe_cost_dollars=probe_measurements.get("cost_dollars", 0.0),
            probe_model=probe_measurements.get("model", "unknown"),
        )
        self._print_warnings(warnings)

        logger.info(
            """
  Tip: use --no-dry-run to skip this confirmation.
       --no-dry-run does not auto-adjust timeouts.""",
        )

        logger.info("%s", Formatters.SEPARATOR_LINE)

        if not Confirm.ask(f"\nProceed with remaining {capped_requests - 1} requests?"):
            logger.info("Aborted by user.")
            raise LoadTestAbortError(0)

        return probe_result

    def _print_summary_header(self, stages: List[int], total_planned_requests: int, capped_requests: int) -> None:
        """
        Print the PRE-RUN SUMMARY header block.

        :param stages: Requests per stage, shown with --ramp
        :param total_planned_requests: Planned requests: sum(stages) * --num-rounds
        :param capped_requests: Requests after the --max-requests cap
        """
        args: Namespace = self._args
        logger.info("\n%s", Formatters.SEPARATOR_LINE)
        logger.info("  PRE-RUN SUMMARY")
        logger.info("%s", Formatters.SEPARATOR_LINE)
        logger.info("  Agent:    %s", args.agent)
        logger.info("  Level:    %s", args.level)
        if args.ramp:
            logger.info("  Stages:   %s", stages)
        round_suffix: str = ""
        if args.num_rounds > 1:
            round_suffix = "s"
        logger.info(
            "  Requests: %s x %s round%s = %s total",
            args.num_requests,
            args.num_rounds,
            round_suffix,
            total_planned_requests,
        )
        if capped_requests < total_planned_requests:
            logger.info("  Capped:   %s (--max-requests)", capped_requests)
        logger.info("  Workers:  %s (concurrent)", args.max_workers)
        # Whole minutes, rounded down, e.g. 150s -> 2m.
        request_timeout_minutes: int = int(args.request_timeout / 60)
        idle_timeout_minutes: int = int(args.idle_timeout / 60)
        stage_timeout_minutes: int = int(args.stage_timeout / 60)
        logger.info(
            "  Timeouts: --request-timeout %ss (%sm) / --idle-timeout %ss (%sm) / --stage-timeout %ss (%sm)",
            args.request_timeout, request_timeout_minutes,
            args.idle_timeout, idle_timeout_minutes,
            args.stage_timeout, stage_timeout_minutes,
        )
        if args.total_timeout > 0:
            # Whole minutes, rounded down, e.g. 150s -> 2m.
            total_timeout_minutes: int = int(args.total_timeout / 60)
            logger.info("            --total-timeout %ss (%sm)", args.total_timeout, total_timeout_minutes)
        else:
            logger.info("            --total-timeout disabled")
        SystemResources.log_prerun()

    @staticmethod
    def _estimate_stage_duration(probe_elapsed_seconds: float, remaining_requests: int) -> float:
        """
        Estimate stage wall time from probe duration.

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
                    f"""Estimated cost exceeds $1:
     Probe used ~{probe_tokens:,} tokens (${probe_cost_dollars:.2f}) x {capped_requests} requests = \
~{estimated_total_tokens:,} tokens (~${estimated_total_cost_dollars:.2f})
     Model: {probe_model}"""
                )

        max_workers: int = self._args.max_workers
        num_requests: int = self._args.num_requests
        if not self._args.ramp and max_workers < num_requests:
            warnings.append(f"--max-workers ({max_workers}) < --num-requests ({num_requests}): requests run in batches")

        if estimated_stage_duration_seconds is not None and estimated_stage_duration_seconds > self._args.stage_timeout:
            stage_timeout_seconds: int = self._args.stage_timeout
            warnings.append(
                f"""Estimated stage duration ~{int(estimated_stage_duration_seconds)}s exceeds --stage-timeout \
({stage_timeout_seconds}s).
     Requests may be killed before completing."""
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
        """
        Warn when the chat filter will suppress token reporting.

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
            no_token_usage_warning: str = """--minimal drops the token-accounting message, and this run has no \
server log to fall back on:
     no LLM or token usage will be reported.
     Omit --minimal to report them."""
            return [no_token_usage_warning]
        no_client_token_warning: str = """--minimal drops the token-accounting message:
     client-side LLM/token numbers will be unavailable (server-log values still apply).
     Omit --minimal to report both."""
        return [no_client_token_warning]

    @staticmethod
    def _check_memory_headroom(num_requests: int) -> Optional[str]:
        """
        Warn if available memory looks insufficient.

        Uses a conservative per-request estimate based on
        typical server thread overhead.

        :param num_requests: Requests that may run at once
        :return: Warning text, or None when available memory looks sufficient
        """
        virtual_memory_stats: Any = virtual_memory()
        available_gigabytes: float = virtual_memory_stats.available / ResourceMonitor.ONE_GIGABYTE
        per_request_megabytes: int = 2
        needed_megabytes: int = num_requests * per_request_megabytes
        needed_gigabytes: float = needed_megabytes / ResourceMonitor.MEGABYTES_PER_GIGABYTE
        if needed_gigabytes > available_gigabytes * 0.8:
            total_gigabytes: float = virtual_memory_stats.total / ResourceMonitor.ONE_GIGABYTE
            memory_warning: str = f"""Memory may be insufficient for {num_requests} concurrent requests:
     Estimated need: ~{needed_gigabytes:.1f} GB ({num_requests} x ~{per_request_megabytes} MB per request)
     Available: {available_gigabytes:.1f} GB / {total_gigabytes:.1f} GB total
     Consider fewer concurrent workers or a larger instance"""
            return memory_warning
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
        warning_number: int
        warning: str
        # Log each warning, numbered from 1, with its extra lines below it.
        for warning_number, warning in enumerate(warnings, 1):
            lines: List[str] = warning.split("\n")
            logger.warning("  %s. %s", warning_number, lines[0])
            line: str
            # Log the rest of the warning's lines.
            for line in lines[1:]:
                logger.warning("  %s", line)

    def _run_cost_probe(self, runner: TrafficRunner,
                        output_dir: Optional[str]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Fire one probe request and return results.

        Fires a single request (tokens are enabled by default)
        and logs the outcome.

        :param runner: Traffic runner used to fire the probe request
        :param output_dir: Directory for the probe's output files, or None
        :return: (probe_result, probe_measurements), where probe_measurements holds tokens, cost_dollars, model and
            elapsed_seconds
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
            "cost_dollars": probe_cost_dollars,
            "model": probe_model,
            "elapsed_seconds": probe_elapsed_seconds,
        }
        return probe_result, probe_measurements
