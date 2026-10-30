
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

from typing import Any
from typing import Dict
from typing import List

from argparse import ArgumentParser
from argparse import Namespace
from argparse import RawDescriptionHelpFormatter
import copy
import json
import os
import sys

from pyparsing.exceptions import ParseException
from pyparsing.exceptions import ParseSyntaxException

from leaf_common.validation.dictionary_validator import DictionaryValidator

from neuro_san.internals.graph.filters.network_config_filter_chain import NetworkConfigFilterChain
from neuro_san.internals.graph.persistence.agent_network_restorer import AgentNetworkRestorer
from neuro_san.internals.validation.network.lint_network_validator import LintNetworkValidator
from neuro_san.internals.validation.network.manifest_network_validator import ManifestNetworkValidator


class HoconValidatorCli:
    """
    Command-line tool for validating HOCON agent network configuration files.

    This script validates HOCON files against neuro-san's agent network validation rules,
    checking for issues such as:
    - Missing or unreachable agents
    - Duplicate agent names
    - Invalid tool names
    - Empty instructions
    - Invalid URL references

    The tool is read-only: it never writes to the filesystem.

    Usage:
        python -m neuro_san.client.hocon_validator_cli path/to/agent.hocon
        python -m neuro_san.client.hocon_validator_cli path/to/agent.hocon --verbose
    """

    def __init__(self):
        """
        Constructor
        """
        self.args: Namespace = None

    def main(self) -> int:
        """
        Main entry point for the HOCON validator CLI.

        :return: Exit code (0 for success, 1 for validation errors, 2 for other errors)
        """
        self.parse_args()

        abs_file_path: str = os.path.abspath(self.args.hocon_file)
        restorer: AgentNetworkRestorer = AgentNetworkRestorer(registry_dir=self.args.registry_dir)

        try:
            raw_config: Dict[str, Any] = self.parse_file(abs_file_path, restorer)
        except FileNotFoundError as exception:
            print(f"Error: File not found - {exception}", file=sys.stderr)
            return 2
        except (ParseException, ParseSyntaxException) as exception:
            print(f"Error: Failed to parse HOCON file - {exception}", file=sys.stderr)
            return 2
        except ValueError as exception:
            print(f"Error: {exception}", file=sys.stderr)
            return 2

        resolved_config: Dict[str, Any] = self.resolve_config(raw_config)

        # Duplicate agent names are a structural failure, not a validation one,
        # so they short-circuit with exit code 2 to match the server's load path.
        duplicate_error: str = self.check_duplicate_agents(restorer, resolved_config, abs_file_path)
        if duplicate_error:
            print(f"Error: {duplicate_error}", file=sys.stderr)
            return 2

        errors: List[str] = self.collect_errors(resolved_config)
        lint: LintNetworkValidator = LintNetworkValidator(raw_config=raw_config)
        unused_warnings: List[str] = lint.find_unused_commondefs()
        placeholder_warnings: List[str] = lint.find_unresolved_placeholders(resolved_config)
        return self.report_results(resolved_config, errors, unused_warnings, placeholder_warnings)

    def collect_errors(self, resolved_config: Dict[str, Any]) -> List[str]:
        """
        Run hard schema/reference checks and return the error messages.

        :param resolved_config: The resolved config to validate
        :return: List of error messages, empty if nothing failed
        """
        validator: DictionaryValidator = self.create_validator()
        errors: List[str] = validator.validate(resolved_config)
        return errors

    def report_results(
        self,
        resolved_config: Dict[str, Any],
        errors: List[str],
        unused_warnings: List[str],
        placeholder_warnings: List[str],
    ) -> int:
        """
        Print validation results to stdout and return the exit code.

        Unused-commondefs warnings are promoted to errors when --strict
        is set; placeholder warnings are always advisory.

        :param resolved_config: The resolved config (used for the verbose summary)
        :param errors: Hard-validation errors
        :param unused_warnings: Unused-commondefs lint warnings
        :param placeholder_warnings: Unresolved-placeholder lint warnings
        :return: Exit code (0 for pass, 1 for errors)
        """
        exit_errors: List[str] = list(errors)
        if self.args.strict:
            exit_errors.extend(unused_warnings)

        if exit_errors:
            print(f"Validation failed with {len(exit_errors)} error(s):\n")
            for index, error in enumerate(exit_errors, 1):
                print(f"  {index}. {error}")
            remaining: List[str] = list(placeholder_warnings)
            if not self.args.strict:
                remaining = unused_warnings + remaining
            if remaining:
                self._print_lint_warnings(remaining)
            return 1

        print("Validation passed: No errors found.")
        all_warnings: List[str] = unused_warnings + placeholder_warnings
        if all_warnings:
            self._print_lint_warnings(all_warnings)
        if self.args.verbose:
            self.print_network_summary(resolved_config)
        return 0

    @staticmethod
    def parse_file(file_path: str, restorer: AgentNetworkRestorer) -> Dict[str, Any]:
        """
        Parse a HOCON file into its raw (pre-filter) config dictionary.

        To make HOCON 'include' statements inside the file resolve against
        the registry layout, this chdirs into the restorer's registry_dir
        for the duration of the parse and restores the previous cwd after.

        :param file_path: Absolute path to the HOCON file
        :param restorer: An AgentNetworkRestorer (used only for its HOCON parser)
        :return: The raw parsed config dictionary
        """
        with open(file_path, "rb") as file_obj:
            file_contents: bytes = file_obj.read()

        registry_dir: str = restorer.registry_dir
        original_cwd: str = os.getcwd()
        # chdir only when a registry_dir is set, so includes resolve relative to it
        if registry_dir and os.path.isdir(registry_dir):
            os.chdir(registry_dir)
        try:
            parsed: Dict[str, Any] = restorer.deserialize_file_contents(file_path, file_contents)
        finally:
            os.chdir(original_cwd)

        if parsed is None:
            raise FileNotFoundError(f"Could not parse file: {file_path}")
        return parsed

    @staticmethod
    def resolve_config(raw_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Apply the standard neuro-san filter chain to produce a resolved
        config suitable for hard validation. Operates on a deep copy so
        the caller's raw config stays intact for the lint checks.

        :param raw_config: The raw, pre-filter config
        :return: The resolved config dictionary
        """
        config_for_filter: Dict[str, Any] = copy.deepcopy(raw_config)
        return NetworkConfigFilterChain().filter_config(config_for_filter)

    @staticmethod
    def check_duplicate_agents(
        restorer: AgentNetworkRestorer, resolved_config: Dict[str, Any], file_path: str
    ) -> str:
        """
        Trigger AgentNetwork's duplicate-name detection by building a
        network from the resolved config. Returns the duplicate-name
        message if the build raises, or an empty string if it passes.
        The underlying message is wrapped in triple-quoted text that
        starts with a newline, so it is stripped before being returned.

        :param restorer: The AgentNetworkRestorer that owns the agent mapper
        :param resolved_config: The filter-chain-applied config
        :param file_path: The HOCON file path (used in the error message)
        :return: The error message string, or an empty string if no duplicates
        """
        try:
            restorer.create_network(resolved_config, file_path)
        except ValueError as exception:
            return str(exception).strip()
        return ""

    @staticmethod
    def _print_lint_warnings(lint_warnings: List[str]):
        """Print lint warnings to stdout."""
        print(f"\n{len(lint_warnings)} lint warning(s) (use --strict to treat these as errors):\n")
        for index, warning in enumerate(lint_warnings, 1):
            print(f"  {index}. {warning}")

    def parse_args(self):
        """
        Parse command line arguments.
        """
        arg_parser: ArgumentParser = ArgumentParser(
            description="Validate a HOCON agent network configuration file.",
            formatter_class=RawDescriptionHelpFormatter,
            epilog="""
Examples:
  python -m neuro_san.client.hocon_validator_cli registries/hello_world.hocon
  python -m neuro_san.client.hocon_validator_cli my_agent.hocon --verbose
            """
        )

        arg_parser.add_argument(
            "hocon_file",
            type=str,
            help="Path to the HOCON file to validate"
        )

        arg_parser.add_argument(
            "--verbose",
            default=False,
            action="store_true",
            help="Print additional information about the agent network"
        )

        arg_parser.add_argument(
            "--external-agents",
            type=str,
            default=None,
            dest="external_agents",
            help="Comma-separated list of valid external agent references (e.g., '/agent1,/agent2')"
        )

        arg_parser.add_argument(
            "--mcp-servers",
            type=str,
            default=None,
            dest="mcp_servers",
            help="Comma-separated list of valid MCP server URLs"
        )

        arg_parser.add_argument(
            "--strict",
            default=False,
            action="store_true",
            help="Treat unused-commondefs lint warnings as validation errors."
        )

        arg_parser.add_argument(
            "--json-output",
            default=False,
            action="store_true",
            dest="json_output",
            help="Output validation results as JSON"
        )

        # Determine default registry directory from AGENT_MANIFEST_FILE if set
        agent_manifest_file: str = os.environ.get("AGENT_MANIFEST_FILE")
        if agent_manifest_file:
            default_registry_dir: str = os.path.dirname(
                os.path.dirname(os.path.abspath(agent_manifest_file))
            )
        else:
            default_registry_dir: str = os.getcwd()

        arg_parser.add_argument(
            "--registry-dir",
            type=str,
            default=default_registry_dir,
            dest="registry_dir",
            help="Base directory containing the registries folder for resolving HOCON includes. "
                 "Defaults to the parent directory of AGENT_MANIFEST_FILE. "
                 "Use this when your HOCON file has includes like 'include \"registries/...\"'"
        )

        self.args = arg_parser.parse_args()

    def create_validator(self) -> DictionaryValidator:
        """
        Create the validator using ManifestNetworkValidator.

        :return: A DictionaryValidator instance
        """
        external_agents: List[str] = None
        if self.args.external_agents:
            external_agents = [agent.strip() for agent in self.args.external_agents.split(",")]

        mcp_servers: List[str] = None
        if self.args.mcp_servers:
            mcp_servers = [server.strip() for server in self.args.mcp_servers.split(",")]

        network_name: str = os.path.basename(self.args.hocon_file)
        return ManifestNetworkValidator(external_agents, mcp_servers, network_name=network_name)

    def print_network_summary(self, config: Dict[str, Any]):
        """
        Print a summary of the agent network.

        :param config: The agent network configuration
        """
        tools: List[Dict[str, Any]] = config.get("tools", [])

        print("\n--- Agent Network Summary ---")
        print(f"Total agents/tools defined: {len(tools)}")

        if tools:
            print("\nAgents:")
            for tool in tools:
                name: str = tool.get("name", "<unnamed>")
                has_instructions: bool = tool.get("instructions") is not None
                sub_tools: List[str] = tool.get("tools", [])
                tool_type: str = "LLM Agent" if has_instructions else "Coded Tool"
                print(f"  - {name} ({tool_type})")
                if sub_tools:
                    print(f"      Sub-tools: {', '.join(str(t) for t in sub_tools)}")

        metadata: Dict[str, Any] = config.get("metadata", {})
        if metadata:
            print(f"\nMetadata: {json.dumps(metadata, indent=2)}")


if __name__ == "__main__":
    sys.exit(HoconValidatorCli().main())
