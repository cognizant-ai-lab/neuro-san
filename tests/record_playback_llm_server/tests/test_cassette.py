
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
Tests for the Cassette on-disk store.
"""
import os

from tests.record_playback_llm_server.cassette import Cassette


class TestCassette:
    """On-disk store: round-trip, atomic save, multi-response de-duplication."""

    def test_put_get_roundtrip(self, tmp_path):
        """A put entry is persisted and re-readable from a fresh Cassette."""
        path = str(tmp_path / "c.json")
        cassette = Cassette(path, use_multi_mode=False)
        cassette.put_response("k1", {"request": "r"}, {"kind": "json", "status": 200})
        assert os.path.exists(path)
        assert Cassette(path, use_multi_mode=False).get("k1")["responses"][0]["status"] == 200

    def test_put_response_dedupes_ignoring_latency(self, tmp_path):
        """Identical response content (differing only in latency) is not duplicated in multi mode."""
        path = str(tmp_path / "c.json")
        cassette = Cassette(path, use_multi_mode=True)
        meta = {"request": "r"}
        cassette.put_response("k", meta, {"kind": "json", "status": 200, "body": {"a": 1}, "latency_seconds": 0.1})
        cassette.put_response("k", meta, {"kind": "json", "status": 200, "body": {"a": 1}, "latency_seconds": 0.9})
        cassette.put_response("k", meta, {"kind": "json", "status": 200, "body": {"a": 2}, "latency_seconds": 0.2})
        assert len(cassette.get("k")["responses"]) == 2

    def test_single_mode_keeps_only_first_response(self, tmp_path):
        """In single-response mode only the first response is retained for a key."""
        path = str(tmp_path / "c.json")
        cassette = Cassette(path, use_multi_mode=False)
        meta = {"request": "r"}
        cassette.put_response("k", meta, {"kind": "json", "status": 200, "body": {"a": 1}})
        cassette.put_response("k", meta, {"kind": "json", "status": 200, "body": {"a": 2}})
        assert len(cassette.get("k")["responses"]) == 1
        assert cassette.get("k")["responses"][0]["body"] == {"a": 1}
