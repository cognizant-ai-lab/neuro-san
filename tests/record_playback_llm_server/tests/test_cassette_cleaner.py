
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
Tests for the CassetteCleaner (strips recorded failures from a cassette).
"""
from tests.record_playback_llm_server.cleanup_cassette import CassetteCleaner


class TestCassetteCleaner:
    """Removing recorded failures while preserving valid entries and unknown fields."""

    def test_clean_entries_mixed(self):
        """Failures are dropped/trimmed; successes and unknown fields survive; stats are correct."""
        entries = [
            {"key": "k1", "response": {"kind": "json", "status": 200}},                       # keep
            {"key": "k2", "response": {"kind": "json", "status": 429}},                        # drop (failure)
            {"key": "k3", "responses": [                                                       # trim to 2xx
                {"kind": "json", "status": 200, "body": {"a": 1}},
                {"kind": "json", "status": 500, "body": {}},
                {"kind": "json", "status": 200, "body": {"a": 2}},
            ]},
            {"key": "k4", "responses": [{"kind": "json", "status": 503}]},                     # drop (all failure)
            {"key": "k5"},                                                                     # drop (malformed)
        ]
        cleaned, stats = CassetteCleaner.clean_entries(entries)
        assert [entry["key"] for entry in cleaned] == ["k1", "k3"]
        assert [r["body"]["a"] for r in cleaned[1]["responses"]] == [1, 2]
        assert stats["kept"] == 2
        assert stats["dropped_failure"] == 2
        assert stats["dropped_malformed"] == 1
        assert stats["variants_removed"] == 1

    def test_clean_is_idempotent(self):
        """Cleaning an already-clean cassette removes nothing."""
        entries = [{"key": "k1", "response": {"kind": "json", "status": 200}}]
        once, _ = CassetteCleaner.clean_entries(entries)
        twice, stats = CassetteCleaner.clean_entries(once)
        assert len(twice) == 1 and stats["dropped_failure"] == 0 and stats["variants_removed"] == 0
