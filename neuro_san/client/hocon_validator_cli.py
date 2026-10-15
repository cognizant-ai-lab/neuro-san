
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
from typing import Tuple

import argparse
import copy
import json
import os
import shutil
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
    - Invalid tool names
    - Empty instructions
    - Invalid URL references

    Usage:
        python -m neuro_san.client.hocon_validator_cli path/to/agent.hocon
        python -m neuro_san.client.hocon_validator_cli path/to/agent.hocon --verbose
    """

    def __init__(self):
        """
        Constructor
        """
        self.args = None

    def main(self) -> int:
        """
        Main entry point for the HOCON validator CLI.

        :return: Exit code (0 for success, 1 for validation errors, 2 for other errors)
        """
        self.parse_args()

        try:
            resolved_config, raw_config = self.load_hocon_file(self.args.hocon_file)
        except FileNotFoundError as exception:
            print(f"Error: File not found - {exception}", file=sys.stderr)
            return 2
        except (ParseException, ParseSyntaxException) as exception:
            print(f"Error: Failed to parse HOCON file - {exception}", file=sys.stderr)
            return 2
        except ValueError as exception:
            print(f"Error: {exception}", file=sys.stderr)
            return 2

        # Run hard validation (missing nodes, cycles, etc.)
        validator: DictionaryValidator = self.create_validator()
        errors: List[str] = validator.validate(resolved_config)

        # Run lint checks: unused commondefs can be promoted to errors
        # by --strict; unresolved placeholders are always advisory.
        lint = LintNetworkValidator(raw_config=raw_config)
        unused_warnings: List[str] = lint.find_unused_commondefs()
        placeholder_warnings: List[str] = lint.find_unresolved_placeholders(resolved_config)

        # Build the list of things that cause exit 1
        exit_errors: List[str] = list(errors)
        if self.args.strict:
            exit_errors.extend(unused_warnings)

        if exit_errors:
            print(f"Validation failed with {len(exit_errors)} error(s):\n")
            for i, error in enumerate(exit_errors, 1):
                print(f"  {i}. {error}")
            # Show remaining warnings that weren't promoted to errors
            remaining: List[str] = list(placeholder_warnings)
            if not self.args.strict:
                remaining = unused_warnings + remaining
            if remaining:
                self._print_lint_warnings(remaining)
            return 1

        # Validation passed
        print("Validation passed: No errors found.")
        all_warnings: List[str] = unused_warnings + placeholder_warnings
        if all_warnings:
            self._print_lint_warnings(all_warnings)
        if self.args.verbose:
            self._print_network_summary(resolved_config)
        return 0

    @staticmethod
    def _print_lint_warnings(lint_warnings: List[str]):
        """Print lint warnings to stdout."""
        print(f"\n{len(lint_warnings)} lint warning(s) (use --strict to treat these as errors):\n")
        for i, warning in enumerate(lint_warnings, 1):
            print(f"  {i}. {warning}")

    def parse_args(self):
        """
        Parse command line arguments.
        """
        arg_parser = argparse.ArgumentParser(
            description="Validate a HOCON agent network configuration file.",
            formatter_class=argparse.RawDescriptionHelpFormatter,
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

    def load_hocon_file(self, file_path: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Load and parse a HOCON file, returning both the resolved and raw configs.

        The file is parsed once. A deep copy is kept as the raw config (needed
        by the unused-commondefs check, which must see definitions before they
        are substituted away), and the standard filter chain is applied to the
        original to produce the resolved config.

        :param file_path: Path to the HOCON file
        :return: (resolved_config, raw_config)
        """
        abs_file_path: str = os.path.abspath(file_path)

        if self.args.registry_dir:
            return self._load_with_registry_dir(abs_file_path, self.args.registry_dir)

        restorer = AgentNetworkRestorer(registry_dir=None)
        return self._parse_and_resolve(abs_file_path, restorer)

    @staticmethod
    def _parse_and_resolve(
        file_path: str, restorer: AgentNetworkRestorer
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Parse a HOCON file once, then produce both raw and resolved configs.

        Uses the restorer's deserialize_file_contents() directly (rather than
        its full restore() path) because restore() applies the filter chain
        *and* wraps the result in an AgentNetwork. We need the parsed dict
        before filtering so we can deep-copy it as the raw config.

        :param file_path: Absolute path to the HOCON file
        :param restorer: An AgentNetworkRestorer (used only for its HOCON parser)
        :return: (resolved_config, raw_config)
        """
        with open(file_path, "rb") as file_obj:
            file_contents: bytes = file_obj.read()

        parsed: Dict[str, Any] = restorer.deserialize_file_contents(
            file_path, file_contents
        )

        if parsed is None:
            raise FileNotFoundError(f"Could not parse file: {file_path}")

        # Keep a deep copy as the raw config before filtering mutates it
        raw_config: Dict[str, Any] = copy.deepcopy(parsed)
        resolved_config: Dict[str, Any] = NetworkConfigFilterChain().filter_config(parsed)
        return resolved_config, raw_config

    def _load_with_registry_dir(
        self, file_path: str, registry_dir: str
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """
        Load a HOCON file by temporarily copying it to the registry directory
        so that HOCON 'include' statements resolve correctly.

        :param file_path: Absolute path to the HOCON file
        :param registry_dir: Directory containing the registries folder
        :return: (resolved_config, raw_config)
        """
        abs_registry_dir: str = os.path.abspath(registry_dir)

        if not os.path.isdir(abs_registry_dir):
            raise ValueError(f"Registry directory does not exist: {abs_registry_dir}")

        temp_file: str = None
        try:
            base_name: str = os.path.basename(file_path)
            temp_file = os.path.join(abs_registry_dir, f"_temp_validate_{base_name}")
            shutil.copy(file_path, temp_file)

            restorer = AgentNetworkRestorer(registry_dir=None)
            return self._parse_and_resolve(temp_file, restorer)
        finally:
            if temp_file and os.path.exists(temp_file):
                os.remove(temp_file)

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
        return ManifestNetworkValidator(external_agents, mcp_servers,
                                        network_name=network_name)

    @staticmethod
    def _print_network_summary(config: Dict[str, Any]):
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
