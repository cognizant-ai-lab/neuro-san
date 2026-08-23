
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

from typing import Dict
from typing import Optional

from tests.record_playback_llm_server.cassette import Cassette
from tests.record_playback_llm_server.playback_delay import PlaybackDelay
from tests.record_playback_llm_server.upstream_client import UpstreamClient


class ProxyState:
    """
    Process-wide state shared across all request handlers of the proxy server:
    which mode it runs in, the cassette store, the client to the real external
    LLM host (record and hybrid modes), and the round-robin rotation
    counters (multi-response playback).

    Modes:
      record    -- forward every request to the real host and store it.
      playback  -- serve only from the cassette; a miss fails hard (504).
      hybrid    -- playback, but on a miss fall through to the real host (if an
                    upstream is configured), record the result into the current
                    cassette, and return it (self-healing playback).
    """

    MODE_RECORD: str = "record"
    MODE_PLAYBACK: str = "playback"
    MODE_HYBRID: str = "hybrid"

    # pylint: disable=too-many-arguments, too-many-positional-arguments
    def __init__(
        self,
        mode: str,
        cassette: Cassette,
        upstream: Optional[UpstreamClient] = None,
        stream_replay_delay: float = 0.0,
        multi_response: bool = False,
        playback_delay: Optional[PlaybackDelay] = None,
    ) -> None:
        """
        :param mode: MODE_RECORD, MODE_PLAYBACK, or MODE_HYBRID.
        :param cassette: The Cassette used for lookup (playback/hybrid) or storage.
        :param upstream: UpstreamClient to the real LLM host; required in record
                         mode, optional in hybrid mode, unused in playback.
        :param stream_replay_delay: Seconds to sleep between streamed SSE frames
                         during playback, to emulate inter-token cadence. 0 = as
                         fast as possible.
        :param multi_response: When True, record/hybrid append each distinct
                         response per request and playback serves them round-robin.
        :param playback_delay: Up-front per-response delay policy applied before
                         serving a cache hit; None means no delay.
        """
        self.mode: str = mode
        self.cassette: Cassette = cassette
        self.upstream: Optional[UpstreamClient] = upstream
        self.stream_replay_delay: float = stream_replay_delay
        self.multi_response: bool = multi_response
        self.playback_delay: PlaybackDelay = playback_delay or PlaybackDelay(PlaybackDelay.MODE_NONE)
        # Per-request round-robin cursor for multi-response playback.
        self._rotation: Dict[str, int] = {}

    def is_record(self) -> bool:
        """:return: True when running in record mode."""
        return self.mode == self.MODE_RECORD

    def is_playback(self) -> bool:
        """:return: True when running in playback mode."""
        return self.mode == self.MODE_PLAYBACK

    def is_hybrid(self) -> bool:
        """:return: True when running in hybrid (record-on-miss) mode."""
        return self.mode == self.MODE_HYBRID

    def next_rotation_index(self, key: str, count: int) -> int:
        """
        Advance and return the round-robin index for a request key.
        :param key: The request signature key.
        :param count: Number of recorded responses available for that key.
        :return: The 0-based index of the response to serve this time.
        """
        index: int = self._rotation.get(key, 0) % count
        self._rotation[key] = index + 1
        return index
