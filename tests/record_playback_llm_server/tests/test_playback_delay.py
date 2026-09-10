
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
Tests for the PlaybackDelay per-response delay policy.
"""
from tests.record_playback_llm_server.playback_delay import PlaybackDelay


class TestPlaybackDelay:
    """Per-response delay policy."""

    def test_none(self):
        """none mode never delays."""
        assert PlaybackDelay(PlaybackDelay.MODE_NONE).seconds_for({"latency_seconds": 1.0}) == 0.0

    def test_recorded_json_uses_latency(self):
        """recorded mode uses latency_seconds for a one-shot response."""
        assert PlaybackDelay(PlaybackDelay.MODE_RECORDED).seconds_for(
            {"kind": "json", "latency_seconds": 1.25}) == 1.25

    def test_recorded_stream_prefers_first_byte(self):
        """recorded mode uses first_byte_seconds for a streamed response."""
        response = {"kind": "stream", "latency_seconds": 5.0, "first_byte_seconds": 0.7}
        assert PlaybackDelay(PlaybackDelay.MODE_RECORDED).seconds_for(response) == 0.7

    def test_recorded_stream_falls_back_to_latency(self):
        """recorded mode falls back to latency_seconds when first_byte is absent."""
        response = {"kind": "stream", "latency_seconds": 5.0, "first_byte_seconds": None}
        assert PlaybackDelay(PlaybackDelay.MODE_RECORDED).seconds_for(response) == 5.0

    def test_recorded_missing_is_zero(self):
        """recorded mode with no recorded latency yields no delay."""
        assert PlaybackDelay(PlaybackDelay.MODE_RECORDED).seconds_for({"kind": "json"}) == 0.0

    def test_fixed(self):
        """fixed mode returns the configured constant."""
        assert PlaybackDelay(PlaybackDelay.MODE_FIXED, fixed_seconds=0.4).seconds_for({}) == 0.4

    def test_random_within_range(self):
        """random mode returns values within the configured range."""
        delay = PlaybackDelay(PlaybackDelay.MODE_RANDOM, min_seconds=0.2, max_seconds=0.5)
        assert all(0.2 <= delay.seconds_for({}) <= 0.5 for _ in range(50))
