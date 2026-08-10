
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
See class comment for details.
"""
from __future__ import annotations

from typing import Optional

from tests.record_playback_llm_server.cassette import Cassette
from tests.record_playback_llm_server.upstream_client import UpstreamClient


class ProxyState:
    """
    Process-wide state shared across all request handlers of the
    record/playback proxy server: which mode it runs in, the cassette store,
    and (in record mode) the client to the real external LLM host.
    """

    MODE_RECORD: str = "record"
    MODE_PLAYBACK: str = "playback"

    def __init__(
        self,
        mode: str,
        cassette: Cassette,
        upstream: Optional[UpstreamClient] = None,
        stream_replay_delay: float = 0.0,
    ) -> None:
        """
        :param mode: MODE_RECORD or MODE_PLAYBACK.
        :param cassette: The Cassette used for lookup (playback) or storage (record).
        :param upstream: UpstreamClient to the real LLM host; required in record
                         mode, unused (None) in playback mode.
        :param stream_replay_delay: Seconds to sleep between streamed SSE frames
                         during playback, to emulate inter-token cadence. 0 = as
                         fast as possible.
        """
        self.mode: str = mode
        self.cassette: Cassette = cassette
        self.upstream: Optional[UpstreamClient] = upstream
        self.stream_replay_delay: float = stream_replay_delay

    def is_record(self) -> bool:
        """:return: True when running in record mode."""
        return self.mode == self.MODE_RECORD

    def is_playback(self) -> bool:
        """:return: True when running in playback mode."""
        return self.mode == self.MODE_PLAYBACK
