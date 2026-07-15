
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
Write/read round-trip tests for LocalReservationsStorage.

Covers: write-then-read of a valid reservation, non-mutation of the
caller's agent_spec, empty-batch no-op, missing-reservation returns
(None, None), and the documented read-path contract that an already-
expired reservation is reported as absent.
"""
import json

import pytest

from neuro_san.service.watcher.temp_networks.local_reservations_storage import LocalReservationsStorage
from tests.neuro_san.service.watcher.temp_networks.local_reservations_test_helpers \
    import LocalReservationsTestHelpers


class TestLocalReservationsStorageWriteRead:
    """
    End-to-end: write a batch, read one back, verify JSON shape and that
    the caller's agent_spec was not mutated.
    """

    @pytest.mark.asyncio
    async def test_write_then_read_round_trip(self, tmp_path):
        """Write a reservation, then read it back and verify JSON shape."""
        storage = LocalReservationsStorage(base_path=str(tmp_path))
        storage.start()

        reservation = LocalReservationsTestHelpers.make_reservation(
            prefix="rt", lifetime_s=3600.0)
        original_spec = LocalReservationsTestHelpers.make_spec()

        await storage.add_reservations({reservation: original_spec},
                                       source="unit-test")

        expected_path = tmp_path / f"{reservation.get_reservation_id()}.json"
        assert expected_path.is_file()

        # File is valid JSON and has the injected metadata block.
        on_disk = json.loads(expected_path.read_text())
        assert on_disk["name"] == "n"
        assert on_disk["llm_config"] == {"model": "gpt"}
        assert "metadata" in on_disk
        assert on_disk["metadata"]["reservation"]["id"] == reservation.get_reservation_id()
        assert "stored_at" in on_disk["metadata"]

        # get_one_reservation reconstructs a working Reservation + AgentNetwork.
        got_reservation, got_network = storage.get_one_reservation(
            reservation.get_reservation_id())
        assert got_reservation is not None
        assert got_reservation.get_reservation_id() == reservation.get_reservation_id()
        assert got_network is not None

    @pytest.mark.asyncio
    async def test_caller_spec_is_not_mutated(self, tmp_path):
        """
        The storage writes a shallow copy of agent_spec; the caller's original
        dict must remain unchanged so callers can safely reuse templates.
        """
        storage = LocalReservationsStorage(base_path=str(tmp_path))
        storage.start()

        reservation = LocalReservationsTestHelpers.make_reservation(
            prefix="nomut", lifetime_s=3600.0)
        original_spec = LocalReservationsTestHelpers.make_spec()
        keys_before = set(original_spec.keys())

        await storage.add_reservations({reservation: original_spec}, source="unit-test")

        assert set(original_spec.keys()) == keys_before, (
            "add_reservations must not add keys to the caller's agent_spec; "
            f"before={keys_before}, after={set(original_spec.keys())}"
        )

    @pytest.mark.asyncio
    async def test_empty_batch_is_no_op(self, tmp_path):
        """add_reservations({}) writes no files and does not raise."""
        storage = LocalReservationsStorage(base_path=str(tmp_path))
        storage.start()

        await storage.add_reservations({}, source="unit-test")

        assert not list(tmp_path.iterdir())

    def test_get_missing_reservation_returns_none(self, tmp_path):
        """Reading a non-existent reservation id returns (None, None) rather than raising."""
        storage = LocalReservationsStorage(base_path=str(tmp_path))
        storage.start()

        got_reservation, got_network = storage.get_one_reservation("nope-does-not-exist")
        assert got_reservation is None
        assert got_network is None

    @pytest.mark.asyncio
    async def test_get_expired_reservation_returns_none(self, tmp_path):
        """
        get_one_reservation() is documented to return (None, None) for
        already-expired entries. Write a reservation whose deadline is in
        the past, then verify the reader does not surface it -- independent
        of the expiration sweep, which is what removes the on-disk file.

        The file may still exist on disk immediately after the read; only
        expire_reservations() deletes it. The point of this test is the
        read-path contract, not the eventual file cleanup.
        """
        storage = LocalReservationsStorage(base_path=str(tmp_path))
        storage.start()

        # Deadline 60 seconds in the past.
        stale = LocalReservationsTestHelpers.make_reservation(
            prefix="stale-read", lifetime_s=60.0, expires_offset_s=-60.0)
        await storage.add_reservations(
            {stale: LocalReservationsTestHelpers.make_spec()}, source="unit-test")

        # File was written -- read path should NOT surface it as valid.
        assert (tmp_path / f"{stale.get_reservation_id()}.json").is_file(), (
            "Expected the writer to persist the file regardless of expiration; "
            "test setup would be wrong otherwise."
        )

        got_reservation, got_network = storage.get_one_reservation(
            stale.get_reservation_id())
        assert got_reservation is None, (
            "get_one_reservation() must not return an expired reservation; "
            "got a non-None reservation from a file with deadline in the past."
        )
        assert got_network is None
