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

"""Command-line interface for the load test.

Holds the argparse definition for every load-test flag, plus the
detection of which flags the user actually passed, which the
orchestrator needs in order to leave explicit values alone when it
applies level-based defaults.
"""

import argparse
import os
from typing import Set

from tests.load_tests.config import DEFAULT_IDLE_TIMEOUT_SECONDS
from tests.load_tests.config import DEFAULT_TIMEOUT_SECONDS
from tests.load_tests.config import LEVEL_ADV
from tests.load_tests.config import LEVEL_MIN
from tests.load_tests.config import LEVEL_NORM
from tests.load_tests.duration import DurationParser


class LoadTestArguments:
    """Defines and parses the load test's command-line arguments."""

    @staticmethod
    def parse_args(epilog) -> argparse.Namespace:
        """Parse command-line arguments for the load test.

        The epilog is supplied by the caller so that ``--help``
        still ends with the entrypoint module's usage notes.
        """
        parser = argparse.ArgumentParser(
            description=(
                "Load-test neuro-san agent networks "
                "with real LLM calls."
            ),
            formatter_class=argparse.RawDescriptionHelpFormatter,
            epilog=epilog,
        )

        parser.add_argument(
            "--agent",
            type=str,
            default="hello_world",
            help="Agent network name to test (default: hello_world). "
                 "Must be registered in the server's "
                 "AGENT_REGISTRY_PATH.",
        )
        parser.add_argument(
            "--profile-path",
            type=str,
            default=os.environ.get("LOAD_TEST_PROFILE_PATH"),
            help="Directory containing agent profile JSON files. "
                 "The filename is derived from --agent "
                 "(e.g. basic/smart_home → smart_home.json). "
                 "Without this, searches built-in profiles/. "
                 "Can also be set via LOAD_TEST_PROFILE_PATH "
                 "env var.",
        )
        parser.add_argument(
            "--project-root",
            type=str,
            default=None,
            help="Path to the project root where the server is "
                 "running from (e.g., /path/to/neuro-san-studio). "
                 "Used to find agent profiles at "
                 "{project-root}/tests/load_tests/prompts/profiles/. "
                 "Falls back to PYTHONPATH if not set.",
        )
        parser.add_argument(
            "--num-requests",
            type=int,
            default=3,
            help="Number of requests per round in flat mode "
                 "(default: 3). Ignored when --ramp is used.",
        )
        parser.add_argument(
            "--max-workers",
            type=int,
            default=3,
            help="Max concurrent workers in flat mode "
                 "(default: 3). At adv level with --no-dry-run, "
                 "auto-matches --num-requests unless "
                 "explicitly set. "
                 "Ignored when --ramp is used.",
        )
        parser.add_argument(
            "--num-rounds",
            type=int,
            default=1,
            help="Number of rounds in flat mode, or number of "
                 "times to repeat the full ramp sequence "
                 "(default: 1).",
        )
        parser.add_argument(
            "--ramp",
            action="store_true",
            default=False,
            help="Enable staged ramp-up mode. Runs escalating "
                 "concurrency stages instead of flat requests.",
        )
        parser.add_argument(
            "--stages",
            type=str,
            default=None,
            help="Comma-separated concurrency levels for ramp-up "
                 "mode (default: 10,30,50,100). "
                 "Only used with --ramp.",
        )
        parser.add_argument(
            "--max-requests",
            type=int,
            default=None,
            help="Hard cap on total requests across all "
                 "stages/rounds. Cost safeguard for real LLM calls."
                 " Default: sum(stages) * num_rounds.",
        )
        parser.add_argument(
            "--host",
            type=str,
            default="localhost",
            help="Neuro-san server host (default: localhost)",
        )
        parser.add_argument(
            "--port",
            type=int,
            default=8080,
            help="Neuro-san server port (default: 8080 for "
                 "http, 443 for https unless overridden)",
        )
        parser.add_argument(
            "--https",
            action="store_true",
            default=False,
            help="Use HTTPS/TLS to reach the server. "
                 "Default is plain HTTP. When set and --port "
                 "is not given, the port defaults to 443.",
        )
        parser.add_argument(
            "--request-timeout",
            type=DurationParser.parse,
            metavar="DURATION",
            default=DEFAULT_TIMEOUT_SECONDS,
            help="Hard timeout per request. Bare number = seconds, "
                 "or suffix s/m/h (e.g. 90s, 20m, 2h). "
                 "Default: 1200 (20m). Safety net to prevent "
                 "requests from running forever.",
        )
        parser.add_argument(
            "--idle-timeout",
            type=DurationParser.parse,
            metavar="DURATION",
            default=DEFAULT_IDLE_TIMEOUT_SECONDS,
            help="Kill a request if no output for this long. Bare "
                 "number = seconds, or suffix s/m/h (e.g. 90s, 15m). "
                 "Default: 900 (15m). Detects hanging requests.",
        )
        parser.add_argument(
            "--stage-timeout",
            type=DurationParser.parse,
            metavar="DURATION",
            default=1500,
            help="Hard timeout for an entire stage/round. Bare "
                 "number = seconds, or suffix s/m/h (e.g. 25m, 1h). "
                 "Default: 1500 (25m). Kills remaining in-flight "
                 "requests when hit.",
        )
        parser.add_argument(
            "--total-timeout",
            type=DurationParser.parse,
            metavar="DURATION",
            default=0,
            help="Hard timeout for the entire load test. Bare "
                 "number = seconds, or suffix s/m/h (e.g. 30m, 2h). "
                 "Default: 0 (disabled). Kills the test run when "
                 "exceeded.",
        )
        parser.add_argument(
            "--settle-time",
            type=DurationParser.parse,
            metavar="DURATION",
            default=15,
            help="Wait this long after each stage for cleanup. Bare "
                 "number = seconds, or suffix s/m/h (e.g. 15s, 1m). "
                 "Default: 15 (15s).",
        )
        parser.add_argument(
            "--same-prompt",
            action="store_true",
            default=False,
            help="Use the same prompt for all requests "
                 "(collision stress test). Default is varied "
                 "prompts from the agent's prompt pool.",
        )
        parser.add_argument(
            "--no-dry-run",
            action="store_true",
            default=False,
            help="Skip the dry-run probe, which otherwise fires one "
                 "real request first and asks you to confirm the "
                 "estimated cost (it runs by default at min/norm; adv "
                 "skips it already). Also auto-matches --max-workers "
                 "to --num-requests at adv level.",
        )
        parser.add_argument(
            "--server-log",
            nargs="?",
            const="auto",
            default=None,
            help="Server log analysis.  Auto-detected by default "
                 "for a local server at norm/adv levels.  Pass a "
                 "path to use a specific file, or --server-log "
                 "with no path to force auto-detect.  Disable with "
                 "--no-server-log.",
        )
        parser.add_argument(
            "--no-server-log",
            action="store_true",
            default=False,
            help="Disable server log analysis (overrides the "
                 "default local auto-detect).",
        )
        parser.add_argument(
            "--archive-server-log",
            action="store_true",
            default=False,
            help="Gzip and copy the server log into the "
                 "output directory after the test completes. "
                 "Requires --server-log.",
        )
        parser.add_argument(
            "--client-only",
            action="store_true",
            default=False,
            help="Client-only mode for split-machine testing. "
                 "Fires requests and monitors client RSS and "
                 "system memory. Skips server process "
                 "detection and server log analysis. "
                 "Mutually exclusive with --server-only.",
        )
        parser.add_argument(
            "--http-client",
            action="store_true",
            default=False,
            help="Use direct HTTP requests instead of "
                 "spawning agent_cli subprocesses. "
                 "Drastically reduces client memory "
                 "(~1 MB vs ~96 MB per concurrent request). "
                 "Implies --client-only.",
        )
        parser.add_argument(
            "--server-only",
            action="store_true",
            default=False,
            help="Server-only mode for split-machine testing. "
                 "Monitors the server process and reads the "
                 "server log while a remote client fires "
                 "requests. Does not fire requests itself. "
                 "Mutually exclusive with --client-only.",
        )
        parser.add_argument(
            "--level",
            type=str,
            choices=[LEVEL_MIN, LEVEL_NORM, LEVEL_ADV],
            default=LEVEL_NORM,
            help="Test depth level (default: norm). "
                 "min: traffic + validation only "
                 "(only with --client-only/--server-only; "
                 "not valid for an all-in-one run). "
                 "norm: adds resource monitoring and "
                 "server log analysis (if --server-log given). "
                 "adv: adds pool analysis "
                 "(defaults to 50 requests, 50 workers, "
                 "3 rounds unless overridden).",
        )
        parser.add_argument(
            "--no-tokens",
            action="store_true",
            default=False,
            help="Disable per-request token accounting. By default "
                 "the load test passes --tokens to agent_cli at "
                 "all levels.",
        )
        parser.add_argument(
            "--minimal",
            dest="chat_filter",
            action="store_const",
            const="minimal",
            default="maximal",
            help="Ask the server for the bare minimum of messages, "
                 "as agent_cli's --minimal does (both subprocess and "
                 "--http-client modes). Streams only the final answer "
                 "instead of all messages including AGENT_PROGRESS, "
                 "which reduces server-to-client traffic and the "
                 "server-side work of producing progress events, but "
                 "also drops the token-accounting message and so "
                 "disables client-side LLM/token reporting (tokens "
                 "then come only from the server log).",
        )
        parser.add_argument(
            "--skip-reservation-check",
            action="store_true",
            default=False,
            help="Skip reservation_id validation. A request is "
                 "marked CREATED if other success fields are "
                 "present, even without a reservation_id.",
        )
        parser.add_argument(
            "--scale",
            type=int,
            default=1,
            help="Multiplier for load parameters. Scales "
                 "--num-requests, --max-workers, "
                 "--request-timeout, --idle-timeout, "
                 "--stage-timeout, and --total-timeout "
                 "by this factor. "
                 "--max-requests auto-adjusts. "
                 "Integer only (default: 1).",
        )
        parser.add_argument(
            "--output-dir",
            type=str,
            default=None,
            help="Base directory for test output. Defaults to "
                 "/tmp/load_test/{level}/{timestamp}.",
        )
        parser.add_argument(
            "--history-file",
            type=str,
            default=None,
            help="Append-only JSONL file recording one trend record "
                 "per client run (completion counts under fixed time "
                 "thresholds + neuro-san version) for plotting over "
                 "time. Defaults to <output-base>/history.jsonl.",
        )
        parser.add_argument(
            "--compare",
            type=str,
            default=None,
            metavar="DIR",
            help="Skip load test; scan DIR for previous "
                 "raw_results.json files and print a "
                 "cross-run comparison table.",
        )
        parser.add_argument(
            "--trend",
            type=str,
            default=None,
            metavar="PATH",
            help="Skip load test; print one row per recorded run "
                 "from the --history-file JSONL, oldest first, so "
                 "throughput can be compared across neuro-san "
                 "versions. PATH is the history file or a directory "
                 "containing history.jsonl. Filtered by "
                 "--compare-agent.",
        )
        parser.add_argument(
            "--compare-agent",
            type=str,
            default=None,
            metavar="NAME",
            help="When used with --compare, show only runs "
                 "for this agent (e.g. hello_world). "
                 "Comma-separated for multiple agents. "
                 "Without this, tables are grouped by agent.",
        )
        parser.add_argument(
            "--compare-baseline",
            type=int,
            default=0,
            metavar="N",
            help="When used with --compare, only show runs "
                 "with at least N requests. The smallest "
                 "remaining run becomes the baseline for "
                 "percentage deltas.",
        )
        parser.add_argument(
            "--compare-runs",
            type=str,
            default=None,
            metavar="FOLDERS",
            help="When used with --compare, show only "
                 "these specific run folders. "
                 "Comma-separated folder names.",
        )
        parser.add_argument(
            "--rebuild",
            type=str,
            default=None,
            metavar="DIR",
            help="Reconstruct raw_results.json from the "
                 "request output files in DIR. Useful for "
                 "runs interrupted by Ctrl+C.",
        )
        parser.add_argument(
            "--rebuild-all",
            action="store_true",
            default=False,
            help="When used with --rebuild on a parent "
                 "directory, rebuild ALL runs including "
                 "those that already have raw_results.json.",
        )
        args = parser.parse_args()
        # Track which args the user explicitly provided so
        # level-based defaults do not override them.
        explicit = LoadTestArguments._explicit_args(parser, args)
        args.explicit_args = explicit
        # When targeting https and no explicit port was given,
        # default to the standard TLS port.
        if args.https and "port" not in explicit:
            args.port = 443
        return args

    @staticmethod
    def _explicit_args(parser, args) -> Set[str]:
        """Return the dest names the user actually passed.

        Re-parses the command line with every default replaced by a
        sentinel, so anything still holding the sentinel was not
        supplied.  This recognizes "--port=8080" as well as
        "--port 8080", and still counts a value that happens to equal
        the default.
        """
        sentinel = object()
        parser.set_defaults(
            **{name: sentinel for name in vars(args)}
        )
        return {
            name
            for name, value in vars(parser.parse_args()).items()
            if value is not sentinel
        }
