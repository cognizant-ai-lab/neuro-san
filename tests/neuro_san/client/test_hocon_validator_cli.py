
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

import contextlib
import io
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
        """Set up test fixtures.

        Paths navigate from this file (tests/neuro_san/client/) up to the
        project root and back into the neuro_san package.
        """
        self.test_dir = os.path.dirname(os.path.abspath(__file__))
        # tests/neuro_san/client -> tests/neuro_san -> tests -> project_root
        self.project_root = os.path.dirname(
            os.path.dirname(os.path.dirname(self.test_dir))
        )
        self.neuro_san_dir = os.path.join(self.project_root, "neuro_san")
        self.registries_dir = os.path.join(self.neuro_san_dir, "registries")

    def _run_cli(self, args):
        """Run the CLI with the given args and capture stdout."""
        stdout = io.StringIO()
        with patch("sys.argv", ["hocon_validator_cli"] + args):
            with contextlib.redirect_stdout(stdout):
                cli = HoconValidatorCli()
                exit_code = cli.main()
        return exit_code, stdout.getvalue()

    def test_valid_hocon_returns_zero(self):
        """Test that a valid HOCON file returns exit code 0."""
        hocon_file = os.path.join(self.registries_dir, "hello_world.hocon")
        exit_code, _ = self._run_cli([hocon_file])
        self.assertEqual(exit_code, 0)

    def test_file_not_found_returns_two(self):
        """Test that a non-existent file returns exit code 2."""
        exit_code, _ = self._run_cli(["/nonexistent/file.hocon"])
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
            exit_code, _ = self._run_cli(
                [temp_file, "--registry-dir", self.project_root]
            )
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
            exit_code, _ = self._run_cli(
                [temp_file, "--registry-dir", self.project_root]
            )
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
            exit_code, _ = self._run_cli(
                [temp_file, "--registry-dir", self.project_root,
                 "--external-agents", "/external_agent"]
            )
            self.assertEqual(exit_code, 0)
        finally:
            os.unlink(temp_file)

    def test_verbose_flag(self):
        """Test that --verbose flag works without errors."""
        hocon_file = os.path.join(self.registries_dir, "hello_world.hocon")
        exit_code, output = self._run_cli([hocon_file, "--verbose"])
        self.assertEqual(exit_code, 0)
        self.assertIn("Agent Network Summary", output)

    def test_lint_warning_does_not_fail_by_default(self):
        """An unused commondef is reported but does not fail without --strict."""
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
            exit_code, output = self._run_cli(
                [temp_file, "--registry-dir", self.project_root]
            )
            self.assertEqual(exit_code, 0)
            self.assertIn("lint warning", output)
            self.assertIn("unused_key", output)
        finally:
            os.unlink(temp_file)

    def test_lint_warning_fails_with_strict_flag(self):
        """An unused commondef fails validation with --strict."""
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
            exit_code, output = self._run_cli(
                [temp_file, "--registry-dir", self.project_root, "--strict"]
            )
            self.assertEqual(exit_code, 1)
            self.assertIn("unused_key", output)
        finally:
            os.unlink(temp_file)

    def test_unresolved_placeholder_is_advisory_only(self):
        """A {word} placeholder is reported but never fails, even with --strict."""
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
            exit_code, output = self._run_cli(
                [temp_file, "--registry-dir", self.project_root]
            )
            self.assertEqual(exit_code, 0)
            self.assertIn("{operation}", output)

            exit_code_strict, output_strict = self._run_cli(
                [temp_file, "--registry-dir", self.project_root, "--strict"]
            )
            self.assertEqual(exit_code_strict, 0)
            self.assertIn("{operation}", output_strict)
        finally:
            os.unlink(temp_file)

    def test_clean_hocon_has_no_lint_warnings(self):
        """A self-contained network with commondefs fully used produces zero warnings."""
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
                }
            ]
        }
        '''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".hocon", delete=False) as f:
            f.write(hocon_content)
            temp_file = f.name
        try:
            exit_code, output = self._run_cli(
                [temp_file, "--registry-dir", self.project_root]
            )
            self.assertEqual(exit_code, 0)
            self.assertNotIn("lint warning", output)
        finally:
            os.unlink(temp_file)

    def test_string_tool_refs_do_not_crash(self):
        """A network with string tool references in replacement_values loads without error."""
        hocon_content = '''
        {
            commondefs: {
                replacement_values: {
                    front_def: {
                        name: "front_man"
                        instructions: "Hi."
                        tools: []
                    }
                }
            }
            tools: [ "front_def" ]
        }
        '''
        with tempfile.NamedTemporaryFile(mode="w", suffix=".hocon", delete=False) as f:
            f.write(hocon_content)
            temp_file = f.name
        try:
            exit_code, _ = self._run_cli(
                [temp_file, "--registry-dir", self.project_root]
            )
            self.assertIn(exit_code, (0, 1))
        finally:
            os.unlink(temp_file)


if __name__ == "__main__":
    unittest.main()
