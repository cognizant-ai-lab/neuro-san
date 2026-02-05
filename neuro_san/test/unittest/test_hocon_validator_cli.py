
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


if __name__ == "__main__":
    unittest.main()
