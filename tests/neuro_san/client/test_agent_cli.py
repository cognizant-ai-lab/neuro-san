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

from contextlib import redirect_stdout
from io import StringIO
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from neuro_san.client import agent_cli as agent_cli_module
from neuro_san.client.agent_cli import AgentCli


class TestAgentCli(unittest.TestCase):
    """
    Tests command-line input handling in AgentCli.
    """

    @staticmethod
    def make_cli() -> AgentCli:
        """
        :return: An AgentCli configured with the arguments used by the input loop.
        """
        cli = AgentCli()
        cli.args = SimpleNamespace(
            thinking_file=None,
            max_input=1,
            tokens=False,
            response_output_file=None,
        )
        return cli

    def test_windows_uses_builtin_input_until_quit(self):
        """
        Windows uses builtin input() and exits when the user enters quit.
        """
        cli = self.make_cli()

        with patch.object(agent_cli_module, "StreamingInputProcessor") as processor_class, \
                patch.object(agent_cli_module.sys, "platform", "win32"), \
                patch.object(agent_cli_module, "timedinput") as timedinput_mock, \
                patch("builtins.input", return_value="quit") as input_mock:
            cli.loop_until_done(None, None, {})

        input_mock.assert_called_once_with(cli.DEFAULT_PROMPT)
        timedinput_mock.assert_not_called()
        processor_class.return_value.process_once.assert_not_called()

    def test_windows_eof_exits(self):
        """
        Windows exits cleanly when stdin is closed.
        """
        cli = self.make_cli()
        output = StringIO()

        with patch.object(agent_cli_module, "StreamingInputProcessor") as processor_class, \
                patch.object(agent_cli_module.sys, "platform", "win32"), \
                patch.object(agent_cli_module, "timedinput") as timedinput_mock, \
                patch("builtins.input", side_effect=EOFError) as input_mock, \
                redirect_stdout(output):
            cli.loop_until_done(None, None, {})

        input_mock.assert_called_once_with(cli.DEFAULT_PROMPT)
        timedinput_mock.assert_not_called()
        processor_class.return_value.process_once.assert_not_called()
        self.assertIn("Stdin closed. Exiting.", output.getvalue())

    def test_posix_timeout_exits(self):
        """
        POSIX exits cleanly when timedinput returns the timeout signal.
        """
        cli = self.make_cli()
        output = StringIO()

        with patch.object(agent_cli_module, "StreamingInputProcessor") as processor_class, \
                patch.object(agent_cli_module.sys, "platform", "linux"), \
                patch.object(agent_cli_module, "timedinput",
                             return_value=cli.TIMEOUT_SIGNAL) as timedinput_mock, \
                patch("builtins.input") as input_mock, \
                redirect_stdout(output):
            cli.loop_until_done(None, None, {})

        timedinput_mock.assert_called_once_with(
            cli.DEFAULT_PROMPT,
            timeout=cli.input_timeout_seconds,
            default=cli.TIMEOUT_SIGNAL,
        )
        input_mock.assert_not_called()
        processor_class.return_value.process_once.assert_not_called()
        self.assertIn(
            f"No input received after {cli.input_timeout_seconds} seconds. Exiting.",
            output.getvalue(),
        )
