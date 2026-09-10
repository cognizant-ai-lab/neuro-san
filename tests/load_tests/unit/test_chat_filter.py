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

"""Unit tests for load-test chat filter command-line handling."""

from unittest.mock import patch

from tests.load_tests.load_test_arguments import LoadTestArguments
from tests.load_tests.traffic.cli_builder import CliBuilder
from tests.load_tests.traffic.http_client import HttpClient


class FakeSession:
    """Stand-in for the HTTP session used by the load-test client."""

    @staticmethod
    def streaming_chat(_request_dict):
        """Return an empty stream; the fake processor does not consume it."""
        return iter(())


class CapturingProcessor:
    """Capture the request state passed to the streaming processor."""

    def __init__(self):
        self.state = None

    def process_once(self, state):
        """Record state and return a successful response."""
        self.state = state
        updated = dict(state)
        updated["last_chat_response"] = "answer"
        return updated


class TestChatFilter:
    """Verifies selection and forwarding of load-test chat filters."""

    def test_default_filter_is_maximal(self, monkeypatch):
        """The load test retains its existing maximal default."""
        monkeypatch.setattr("sys.argv", ["load_test"])

        args = LoadTestArguments.parse_args(epilog=None)

        assert args.chat_filter == "maximal"

    def test_minimal_selects_minimal_filter(self, monkeypatch):
        """The --minimal option selects the minimal filter."""
        monkeypatch.setattr("sys.argv", ["load_test", "--minimal"])

        args = LoadTestArguments.parse_args(epilog=None)

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

    def test_maximal_filter_is_not_forwarded_as_minimal(self):
        """Subprocess traffic retains agent_cli's maximal default."""
        command = CliBuilder.build_cli_command(
            "localhost",
            8080,
            "hello_world",
            "prompt.txt",
            chat_filter_type="MAXIMAL",
        )

        assert "--minimal" not in command

    def test_minimal_filter_is_forwarded_to_http_request(self):
        """HTTP traffic places the minimal filter in request state."""
        session = FakeSession()
        processor = CapturingProcessor()
        with patch(
            "tests.load_tests.traffic.http_client."
            "HttpServiceAgentSession",
            return_value=session,
        ), patch(
            "tests.load_tests.traffic.http_client."
            "StreamingInputProcessor",
            return_value=processor,
        ):
            HttpClient.execute_request(
                "localhost",
                8080,
                "hello_world",
                "prompt",
                timeout=30,
                idle_timeout=30,
                chat_filter_type="MINIMAL",
            )

        assert processor.state["chat_filter"] == {
            "chat_filter_type": "MINIMAL",
        }
