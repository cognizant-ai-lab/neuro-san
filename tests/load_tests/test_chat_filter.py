# Copyright © 2023-2026 Cognizant Technology Solutions Corp, www.cognizant.com.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# END COPYRIGHT

"""Unit tests for load-test chat filter command-line handling."""

from tests.load_tests.load_test import LoadTestOrchestrator
from tests.load_tests.traffic.cli_builder import CliBuilder


class TestChatFilter:
    """Verifies selection and forwarding of the minimal chat filter."""

    def test_default_filter_is_maximal(self, monkeypatch):
        """The load test retains its existing maximal default."""
        monkeypatch.setattr("sys.argv", ["load_test"])

        args = LoadTestOrchestrator.parse_args()

        assert args.chat_filter == "maximal"

    def test_chat_filter_accepts_minimal(self, monkeypatch):
        """The explicit chat filter option accepts minimal."""
        monkeypatch.setattr(
            "sys.argv",
            ["load_test", "--chat-filter", "minimal"],
        )

        args = LoadTestOrchestrator.parse_args()

        assert args.chat_filter == "minimal"

    def test_minimal_filter_is_forwarded_to_agent_cli(self):
        """Subprocess traffic translates the filter to agent_cli syntax."""
        command = CliBuilder.build_cli_command(
            "localhost",
            8080,
            "hello_world",
            "prompt.txt",
            chat_filter_type="MINIMAL",
        )

        assert "--minimal" in command
