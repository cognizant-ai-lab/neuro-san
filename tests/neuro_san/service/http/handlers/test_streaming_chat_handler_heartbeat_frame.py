
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
"""
Unit tests for StreamingChatHandler._build_heartbeat_frame().

The handler pre-builds the heartbeat wire frame once at initialize() time
and writes it verbatim per tick. The frame must:
  - wrap a JSON ChatMessage payload in the {"response": ...} envelope so
    clients see the same shape as real chat responses;
  - end in a newline so JSON-Lines framing remains intact even when the
    heartbeat lands between two real messages;
  - fall back to passing non-JSON payloads through with a trailing newline,
    preserving the legacy "\\n" default's behavior.
"""

import json

from neuro_san.service.http.handlers.streaming_chat_handler import StreamingChatHandler


# These tests exercise a deliberately-internal helper directly; suppress
# protected-access warnings file-wide rather than at each call site.
# pylint: disable=protected-access
class TestStreamingChatHandlerHeartbeatFrame:
    """
    Direct tests for the static frame builder. No Tornado runtime is
    required because the method does not touch instance state.
    """

    # ---- JSON ChatMessage payloads (the primary path) -----------------------

    def test_agent_progress_payload_is_wrapped_in_response_envelope(self):
        """
        The Dockerfile-default AGENT_PROGRESS payload is wrapped in
        {"response": ...} and a trailing newline is appended.
        """
        configured = '{"type": 104, "text": ""}'
        frame = StreamingChatHandler._build_heartbeat_frame(configured)

        assert frame.endswith("\n"), "Heartbeat frame must end with a newline for JSON-Lines framing."
        # Parsing the line (minus the newline) must yield a ChatResponse-shaped dict.
        parsed = json.loads(frame.rstrip("\n"))
        assert parsed == {"response": {"type": 104, "text": ""}}, (
            f"Expected the configured ChatMessage to be wrapped in 'response'; got {parsed}."
        )

    def test_string_type_agent_progress_payload_is_wrapped(self):
        """
        The string-name form of the type field (matching what
        ChatMessageConverter emits for real messages) is wrapped the same way.
        """
        configured = '{"type": "AGENT_PROGRESS", "text": ""}'
        frame = StreamingChatHandler._build_heartbeat_frame(configured)

        parsed = json.loads(frame.rstrip("\n"))
        assert parsed == {"response": {"type": "AGENT_PROGRESS", "text": ""}}

    def test_payload_with_extra_fields_is_wrapped_verbatim(self):
        """
        Extra fields on the configured ChatMessage are passed through into
        the wrapped envelope unchanged -- the builder must not strip them.
        """
        configured = '{"type": "AGENT_PROGRESS", "text": "ping", "structure": {"k": 1}}'
        frame = StreamingChatHandler._build_heartbeat_frame(configured)

        parsed = json.loads(frame.rstrip("\n"))
        assert parsed == {
            "response": {"type": "AGENT_PROGRESS", "text": "ping", "structure": {"k": 1}}
        }

    # ---- Legacy / fallback non-JSON payloads --------------------------------

    def test_legacy_newline_payload_passes_through(self):
        """
        The historical default heartbeat payload of "\\n" must be sent on
        the wire unchanged, since it is already a valid JSON-Lines frame
        (a blank line that all JSON-Lines parsers tolerate).
        """
        assert StreamingChatHandler._build_heartbeat_frame("\n") == "\n"

    def test_non_json_string_gets_newline_appended(self):
        """
        A non-JSON heartbeat payload (e.g. a plain string sentinel) is
        passed through with a newline appended for framing.
        """
        assert StreamingChatHandler._build_heartbeat_frame("ping") == "ping\n"

    def test_non_json_string_with_trailing_newline_is_not_double_terminated(self):
        """
        A non-JSON payload that already ends in a newline must not get a
        second newline appended.
        """
        assert StreamingChatHandler._build_heartbeat_frame("ping\n") == "ping\n"

    def test_empty_string_payload_is_terminated(self):
        """
        Empty configured payload -- which json.loads treats as invalid --
        yields a single newline frame.
        """
        assert StreamingChatHandler._build_heartbeat_frame("") == "\n"
