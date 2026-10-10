
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
from typing import Type

import argparse
import json
import os
import shutil
import sys

from pyparsing.exceptions import ParseException
from pyparsing.exceptions import ParseSyntaxException

from leaf_common.validation.dictionary_validator import DictionaryValidator

from neuro_san.internals.graph.persistence.agent_network_restorer import AgentNetworkRestorer
from neuro_san.internals.graph.persistence.raw_agent_network_restorer import RawAgentNetworkRestorer
from neuro_san.internals.validation.hocon_lint import find_unresolved_replacement_strings
from neuro_san.internals.validation.hocon_lint import find_unset_allow_sly_data_keys
from neuro_san.internals.validation.hocon_lint import find_unused_commondefs
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
            config: Dict[str, Any] = self.load_hocon_file(self.args.hocon_file)
        except FileNotFoundError as exception:
            print(f"Error: File not found - {exception}", file=sys.stderr)
            return 2
        except (ParseException, ParseSyntaxException) as exception:
            print(f"Error: Failed to parse HOCON file - {exception}", file=sys.stderr)
            return 2
        except ValueError as exception:
            print(f"Error: {exception}", file=sys.stderr)
            return 2

        # Also load the raw, pre-commondefs-substitution config.
        # Used only by find_unused_commondefs(), which needs to see
        # definitions that would otherwise be resolved away. Loaded
        # separately since the standard validation path above expects
        # (and the server always uses) the fully-resolved config.
        raw_config: Dict[str, Any] = None
        try:
            raw_config = self.load_hocon_file(self.args.hocon_file, restorer_class=RawAgentNetworkRestorer)
        except (FileNotFoundError, ParseException, ParseSyntaxException, ValueError):
            # Already reported above when loading the resolved config; nothing new to say here.
            pass

        validator: DictionaryValidator = self.create_validator()
        errors: List[str] = validator.validate(config)

        lint_warnings: List[str] = self.find_lint_warnings(config, raw_config)

        exit_errors: List[str] = list(errors)
        if self.args.strict:
            exit_errors.extend(lint_warnings)

        if exit_errors:
            print(f"Validation failed with {len(exit_errors)} error(s):\n")
            for i, error in enumerate(exit_errors, 1):
                print(f"  {i}. {error}")
            if not self.args.strict and lint_warnings:
                self.print_lint_warnings(lint_warnings)
            return 1

        print("Validation passed: No errors found.")
        if lint_warnings:
            self.print_lint_warnings(lint_warnings)
        if self.args.verbose:
            self.print_network_summary(config)
        return 0

    @staticmethod
    def find_lint_warnings(config: Dict[str, Any], raw_config: Dict[str, Any]) -> List[str]:
        """
        Run the best-effort lint checks over a validated agent network.

        :param config: The fully-resolved agent network config dictionary
        :param raw_config: The pre-commondefs-substitution config dictionary,
                or None if it could not be loaded
        :return: A list of human-readable warning strings
        """
        lint_warnings: List[str] = []
        if raw_config is not None:
            lint_warnings.extend(find_unused_commondefs(raw_config))
        lint_warnings.extend(find_unresolved_replacement_strings(config))
        lint_warnings.extend(find_unset_allow_sly_data_keys(config))
        return lint_warnings

    @staticmethod
    def print_lint_warnings(lint_warnings: List[str]):
        """
        :param lint_warnings: The list of lint warning strings to print
        """
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
            help="Treat lint warnings (unused commondefs, unresolved {replacement} strings, "
                 "and allow.*.sly_data keys not declared in any sly_data_schema) as validation "
                 "errors instead of printing them separately."
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

    def load_hocon_file(self, file_path: str,
                        restorer_class: Type[AgentNetworkRestorer] = AgentNetworkRestorer) -> Dict[str, Any]:
        """
        Load and parse a HOCON file.

        If registry_dir is specified, the file is temporarily copied to that directory
        so that HOCON includes (like 'include "registries/..."') can be resolved correctly.

        :param file_path: Path to the HOCON file
        :param restorer_class: The AgentNetworkRestorer subclass to use. Defaults to
                AgentNetworkRestorer itself (the standard, fully-resolved config).
                Pass RawAgentNetworkRestorer to get the pre-commondefs-substitution config.
        :return: Parsed configuration dictionary
        """
        abs_file_path: str = os.path.abspath(file_path)

        if self.args.registry_dir:
            return self._load_with_registry_dir(abs_file_path, self.args.registry_dir, restorer_class)

        restorer = restorer_class(registry_dir=None)
        agent_network = restorer.restore(file_reference=abs_file_path)
        return agent_network.get_config()

    def _load_with_registry_dir(self, file_path: str, registry_dir: str,
                                restorer_class: Type[AgentNetworkRestorer] = AgentNetworkRestorer) -> Dict[str, Any]:
        """
        Load a HOCON file by temporarily copying it to the registry directory.

        This allows HOCON includes to be resolved relative to the registry directory.

        :param file_path: Absolute path to the HOCON file
        :param registry_dir: Directory containing the registries folder
        :param restorer_class: The AgentNetworkRestorer subclass to use. See load_hocon_file().
        :return: Parsed configuration dictionary
        """
        abs_registry_dir: str = os.path.abspath(registry_dir)

        if not os.path.isdir(abs_registry_dir):
            raise ValueError(f"Registry directory does not exist: {abs_registry_dir}")

        temp_file: str = None
        try:
            base_name: str = os.path.basename(file_path)
            temp_file = os.path.join(abs_registry_dir, f"_temp_validate_{base_name}")

            shutil.copy(file_path, temp_file)

            restorer = restorer_class(registry_dir=None)
            agent_network = restorer.restore(file_reference=temp_file)
            return agent_network.get_config()
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
