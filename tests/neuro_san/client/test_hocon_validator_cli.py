
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

from typing import List
from typing import Tuple
from unittest.mock import patch

from neuro_san.client.hocon_validator_cli import HoconValidatorCli


class TestHoconValidatorCli(unittest.TestCase):
    """
    Unit tests for the HoconValidatorCli class.
    """

    # Reused by the two strict/non-strict lint tests
    UNUSED_COMMONDEF_HOCON: str = """
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
    """

    def setUp(self):
        """
        Resolve paths relative to this test file so the registry directory
        can be passed to the CLI without depending on the caller's cwd.
        """
        self.test_dir = os.path.dirname(os.path.abspath(__file__))
        # tests/neuro_san/client -> tests/neuro_san -> tests -> project_root
        self.project_root = os.path.dirname(os.path.dirname(os.path.dirname(self.test_dir)))
        self.neuro_san_dir = os.path.join(self.project_root, "neuro_san")
        self.registries_dir = os.path.join(self.neuro_san_dir, "registries")

    def _run_cli(self, args: List[str]) -> Tuple[int, str]:
        """
        Run the CLI with the given args and capture stdout.

        :param args: Argv tail (everything after the program name)
        :return: (exit_code, captured_stdout)
        """
        stdout = io.StringIO()
        with patch("sys.argv", ["hocon_validator_cli"] + args):
            with contextlib.redirect_stdout(stdout):
                cli = HoconValidatorCli()
                exit_code = cli.main()
        return exit_code, stdout.getvalue()

    def _run_cli_on_hocon(self, hocon_content: str, extra_args: List[str] = None) -> Tuple[int, str]:
        """
        Write hocon_content to a temp file, run the CLI against it with
        --registry-dir set to the project root plus any extra args, and
        clean up the temp file afterwards.

        :param hocon_content: Raw HOCON source to validate
        :param extra_args: Additional CLI args appended after --registry-dir
        :return: (exit_code, captured_stdout)
        """
        with tempfile.NamedTemporaryFile(mode="w", suffix=".hocon", delete=False) as hocon_handle:
            hocon_handle.write(hocon_content)
            temp_path: str = hocon_handle.name
        try:
            args: List[str] = [temp_path, "--registry-dir", self.project_root]
            if extra_args:
                args.extend(extra_args)
            return self._run_cli(args)
        finally:
            os.unlink(temp_path)

    def test_valid_hocon_returns_zero(self):
        """A valid HOCON file returns exit code 0."""
        hocon_file: str = os.path.join(self.registries_dir, "hello_world.hocon")
        exit_code, _ = self._run_cli([hocon_file])
        self.assertEqual(exit_code, 0)

    def test_file_not_found_returns_two(self):
        """A non-existent file returns exit code 2."""
        exit_code, _ = self._run_cli(["/nonexistent/file.hocon"])
        self.assertEqual(exit_code, 2)

    def test_missing_agent_returns_one(self):
        """A HOCON with a missing agent reference returns exit code 1."""
        hocon_content: str = """
        {
            tools: [
                {
                    name: "test_agent"
                    instructions: "Test instructions"
                    tools: ["nonexistent_tool"]
                }
            ]
        }
        """
        exit_code, _ = self._run_cli_on_hocon(hocon_content)
        self.assertEqual(exit_code, 1)

    def test_unreachable_agent_returns_one(self):
        """A HOCON with an unreachable agent returns exit code 1."""
        hocon_content: str = """
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
        """
        exit_code, _ = self._run_cli_on_hocon(hocon_content)
        self.assertEqual(exit_code, 1)

    def test_duplicate_agent_name_returns_two(self):
        """A HOCON with two agents sharing a name is a structural failure (exit 2)."""
        hocon_content: str = """
        {
            tools: [
                {
                    name: "helper"
                    instructions: "First helper"
                    tools: []
                },
                {
                    name: "helper"
                    instructions: "Second helper"
                    tools: []
                }
            ]
        }
        """
        # Duplicate names go to stderr; collect it alongside stdout
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            exit_code, _ = self._run_cli_on_hocon(hocon_content)
        self.assertEqual(exit_code, 2)
        self.assertIn("duplicate entry", stderr.getvalue())

    def test_external_agents_flag(self):
        """--external-agents allows references to external agents."""
        hocon_content: str = """
        {
            tools: [
                {
                    name: "test_agent"
                    instructions: "Test instructions"
                    tools: ["/external_agent"]
                }
            ]
        }
        """
        exit_code, _ = self._run_cli_on_hocon(hocon_content, ["--external-agents", "/external_agent"])
        self.assertEqual(exit_code, 0)

    def test_verbose_flag(self):
        """--verbose prints a network summary without errors."""
        hocon_file: str = os.path.join(self.registries_dir, "hello_world.hocon")
        exit_code, output = self._run_cli([hocon_file, "--verbose"])
        self.assertEqual(exit_code, 0)
        self.assertIn("Agent Network Summary", output)

    def test_lint_warning_does_not_fail_by_default(self):
        """An unused commondef is reported but does not fail without --strict."""
        exit_code, output = self._run_cli_on_hocon(self.UNUSED_COMMONDEF_HOCON)
        self.assertEqual(exit_code, 0)
        self.assertIn("lint warning", output)
        self.assertIn("unused_key", output)

    def test_lint_warning_fails_with_strict_flag(self):
        """An unused commondef fails validation with --strict."""
        exit_code, output = self._run_cli_on_hocon(self.UNUSED_COMMONDEF_HOCON, ["--strict"])
        self.assertEqual(exit_code, 1)
        self.assertIn("unused_key", output)

    def test_unresolved_placeholder_is_advisory_only(self):
        """A {word} placeholder is reported but never fails, even with --strict."""
        hocon_content: str = """
        {
            tools: [
                {
                    name: "test_agent"
                    instructions: "Perform the {operation} operation."
                    tools: []
                }
            ]
        }
        """
        exit_code, output = self._run_cli_on_hocon(hocon_content)
        self.assertEqual(exit_code, 0)
        self.assertIn("{operation}", output)

        exit_code_strict, output_strict = self._run_cli_on_hocon(hocon_content, ["--strict"])
        self.assertEqual(exit_code_strict, 0)
        self.assertIn("{operation}", output_strict)

    def test_clean_hocon_has_no_lint_warnings(self):
        """A self-contained network with commondefs fully used produces zero warnings."""
        hocon_content: str = """
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
        """
        exit_code, output = self._run_cli_on_hocon(hocon_content)
        self.assertEqual(exit_code, 0)
        self.assertNotIn("lint warning", output)

    def test_string_tool_refs_pass_validation(self):
        """A network with string tool references in replacement_values validates cleanly."""
        hocon_content: str = """
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
        """
        exit_code, _ = self._run_cli_on_hocon(hocon_content)
        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
