
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

import os
import tempfile
import unittest

from unittest.mock import patch

from neuro_san.client.hocon_validator_cli import HoconValidatorCli
from neuro_san.internals.graph.persistence.raw_agent_network_restorer import RawAgentNetworkRestorer


class TestHoconValidatorCli(unittest.TestCase):
    """
    Unit tests for the HoconValidatorCli class.
    """

    def setUp(self):
        """Set up test fixtures."""
        self.test_dir = os.path.dirname(os.path.abspath(__file__))
        self.neuro_san_dir = os.path.dirname(os.path.dirname(self.test_dir))
        self.registries_dir = os.path.join(self.neuro_san_dir, "registries")

    def test_valid_hocon_returns_zero(self):
        """Test that a valid HOCON file returns exit code 0."""
        hocon_file = os.path.join(self.registries_dir, "hello_world.hocon")
        with patch("sys.argv", ["hocon_validator_cli", hocon_file]):
            cli = HoconValidatorCli()
            exit_code = cli.main()
        self.assertEqual(exit_code, 0)

    def test_file_not_found_returns_two(self):
        """Test that a non-existent file returns exit code 2."""
        with patch("sys.argv", ["hocon_validator_cli", "/nonexistent/file.hocon"]):
            cli = HoconValidatorCli()
            exit_code = cli.main()
        self.assertEqual(exit_code, 2)

    def test_missing_agent_returns_one(self):
        """Test that a HOCON with missing agent reference returns exit code 1."""
        hocon_content = '''
        {
            tools: [
                {
                    name: "test_agent"
                    instructions: "Test instructions"
                    tools: ["nonexistent_tool"]
                }
            ]
        }
        '''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".hocon", delete=False) as f:
            f.write(hocon_content)
            temp_file = f.name
        try:
            with patch("sys.argv", ["hocon_validator_cli", temp_file, "--registry-dir", self.neuro_san_dir]):
                cli = HoconValidatorCli()
                exit_code = cli.main()
            self.assertEqual(exit_code, 1)
        finally:
            os.unlink(temp_file)

    def test_unreachable_agent_returns_one(self):
        """Test that a HOCON with unreachable agent returns exit code 1."""
        hocon_content = '''
        {
            tools: [
                {
                    name: "main_agent"
                    instructions: "Main agent"
                    tools: []
                },
                {
                    name: "orphan_agent"
                    instructions: "This agent is never referenced"
                    tools: []
                }
            ]
        }
        '''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".hocon", delete=False) as f:
            f.write(hocon_content)
            temp_file = f.name
        try:
            with patch("sys.argv", ["hocon_validator_cli", temp_file, "--registry-dir", self.neuro_san_dir]):
                cli = HoconValidatorCli()
                exit_code = cli.main()
            self.assertEqual(exit_code, 1)
        finally:
            os.unlink(temp_file)

    def test_external_agents_flag(self):
        """Test that --external-agents flag allows external agent references."""
        hocon_content = '''
        {
            tools: [
                {
                    name: "test_agent"
                    instructions: "Test instructions"
                    tools: ["/external_agent"]
                }
            ]
        }
        '''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".hocon", delete=False) as f:
            f.write(hocon_content)
            temp_file = f.name
        try:
            with patch("sys.argv", ["hocon_validator_cli", temp_file,
                                    "--registry-dir", self.neuro_san_dir,
                                    "--external-agents", "/external_agent"]):
                cli = HoconValidatorCli()
                exit_code = cli.main()
            self.assertEqual(exit_code, 0)
        finally:
            os.unlink(temp_file)

    def test_verbose_flag(self):
        """Test that --verbose flag works without errors."""
        hocon_file = os.path.join(self.registries_dir, "hello_world.hocon")
        with patch("sys.argv", ["hocon_validator_cli", hocon_file, "--verbose"]):
            cli = HoconValidatorCli()
            exit_code = cli.main()
        self.assertEqual(exit_code, 0)

    def test_lint_warning_does_not_fail_by_default(self):
        """An unused commondef is reported but does not fail validation without --strict."""
        hocon_content = '''
        {
            commondefs: {
                replacement_strings: {
                    unused_key: "never referenced"
                }
            }
            tools: [
                {
                    name: "test_agent"
                    instructions: "Test instructions"
                    tools: []
                }
            ]
        }
        '''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".hocon", delete=False) as f:
            f.write(hocon_content)
            temp_file = f.name
        try:
            with patch("sys.argv", ["hocon_validator_cli", temp_file, "--registry-dir", self.neuro_san_dir]):
                cli = HoconValidatorCli()
                exit_code = cli.main()
            self.assertEqual(exit_code, 0)
        finally:
            os.unlink(temp_file)

    def test_lint_warning_fails_with_strict_flag(self):
        """The same unused commondef fails validation once --strict is passed."""
        hocon_content = '''
        {
            commondefs: {
                replacement_strings: {
                    unused_key: "never referenced"
                }
            }
            tools: [
                {
                    name: "test_agent"
                    instructions: "Test instructions"
                    tools: []
                }
            ]
        }
        '''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".hocon", delete=False) as f:
            f.write(hocon_content)
            temp_file = f.name
        try:
            with patch("sys.argv", ["hocon_validator_cli", temp_file,
                                    "--registry-dir", self.neuro_san_dir, "--strict"]):
                cli = HoconValidatorCli()
                exit_code = cli.main()
            self.assertEqual(exit_code, 1)
        finally:
            os.unlink(temp_file)

    def test_unresolved_replacement_string_is_flagged(self):
        """A {word} placeholder with no matching commondef is reported as a lint warning."""
        hocon_content = '''
        {
            tools: [
                {
                    name: "test_agent"
                    instructions: "Perform the {operation} operation."
                    tools: []
                }
            ]
        }
        '''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".hocon", delete=False) as f:
            f.write(hocon_content)
            temp_file = f.name
        try:
            with patch("sys.argv", ["hocon_validator_cli", temp_file, "--registry-dir", self.neuro_san_dir]):
                cli = HoconValidatorCli()
                exit_code = cli.main()
            self.assertEqual(exit_code, 0)
            with patch("sys.argv", ["hocon_validator_cli", temp_file,
                                    "--registry-dir", self.neuro_san_dir, "--strict"]):
                cli = HoconValidatorCli()
                exit_code = cli.main()
            self.assertEqual(exit_code, 1)
        finally:
            os.unlink(temp_file)

    def test_clean_hocon_has_no_lint_warnings(self):
        """A self-contained network with commondefs fully used, no leftover placeholders,
        and all allow.sly_data keys declared produces zero lint warnings across all three checks."""
        hocon_content = '''
        {
            commondefs: {
                replacement_strings: {
                    role: "assistant"
                }
            }
            tools: [
                {
                    name: "front_man"
                    instructions: "You are a {role}."
                    tools: ["worker"]
                },
                {
                    name: "worker"
                    instructions: "Supporting {role} for front_man."
                    function: {
                        sly_data_schema: {
                            type: object
                            properties: { session_id: { type: string } }
                        }
                    }
                    allow: { to_upstream: { sly_data: ["session_id"] } }
                }
            ]
        }
        '''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".hocon", delete=False) as f:
            f.write(hocon_content)
            temp_file = f.name
        try:
            with patch("sys.argv", ["hocon_validator_cli", temp_file, "--registry-dir", self.neuro_san_dir]):
                cli = HoconValidatorCli()
                cli.parse_args()
                config = cli.load_hocon_file(temp_file)
                raw_config = cli.load_hocon_file(temp_file, restorer_class=RawAgentNetworkRestorer)
                lint_warnings = cli.find_lint_warnings(config, raw_config)
            self.assertEqual(lint_warnings, [])
        finally:
            os.unlink(temp_file)


if __name__ == "__main__":
    unittest.main()
