
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
Unit tests for LocalReservationsStorage.

Covers the main paths: construction (with and without env-var fallback),
write, read round-trip, missing-key handling, expiration sweep, and
non-mutation of the caller's agent_spec. Uses a tmp_path fixture so each
test runs in an isolated directory; no server, no threads, no shared state.
"""
import json
import os
import time
from typing import Any
from typing import Dict

import pytest

from neuro_san.internals.reservations.agent_reservation import AgentReservation
from neuro_san.service.watcher.temp_networks.local_reservations_storage import LocalReservationsStorage


def _make_reservation(prefix: str, lifetime_s: float,
                      expires_offset_s: float = None) -> AgentReservation:
    """
    Build an AgentReservation with a deterministic expiration.

    :param prefix: The prefix used to build the reservation id.
    :param lifetime_s: Lifetime handed to the AgentReservation constructor.
    :param expires_offset_s: Offset (in seconds) from now that the reservation
                             should expire. Positive = future, negative = past.
                             When None, defaults to `lifetime_s`.
    """
    reservation = AgentReservation(lifetime_in_seconds=lifetime_s, prefix=prefix)
    offset: float = lifetime_s if expires_offset_s is None else expires_offset_s
    now: float = time.time()
    # set_expiration_from clamps to min(lifetime, max_lifetime), so pass a big
    # max_lifetime and let `use_now_in_seconds` set the deadline where we want.
    reservation.set_expiration_from(use_now_in_seconds=now + offset - lifetime_s,
                                    max_lifetime_in_seconds=lifetime_s + 1.0)
    return reservation


def _make_spec() -> Dict[str, Any]:
    return {"name": "n", "llm_config": {"model": "gpt"}, "tools": []}


class TestLocalReservationsStorageConstructor:
    """
    Constructor validation: path can come from the base_path arg or the
    AGENT_RESERVATIONS_LOCAL_PATH env var; missing both is an error.
    """

    def test_missing_path_raises(self, monkeypatch):
        """No base_path arg and no env var -> ValueError."""
        monkeypatch.delenv("AGENT_RESERVATIONS_LOCAL_PATH", raising=False)
        with pytest.raises(ValueError, match="Local path for reservations"):
            LocalReservationsStorage()

    def test_env_var_fallback(self, monkeypatch, tmp_path):
        """base_path defaults from the env var when the arg is empty."""
        monkeypatch.setenv("AGENT_RESERVATIONS_LOCAL_PATH", str(tmp_path))
        storage = LocalReservationsStorage()
        assert storage.base_path == str(tmp_path.resolve())

    def test_explicit_arg_wins_over_env(self, monkeypatch, tmp_path):
        """A non-empty base_path arg is used even when the env var is set."""
        monkeypatch.setenv("AGENT_RESERVATIONS_LOCAL_PATH", "/some/env/path")
        storage = LocalReservationsStorage(base_path=str(tmp_path))
        assert storage.base_path == str(tmp_path.resolve())


class TestLocalReservationsStorageStart:
    """start() creates the storage directory if it does not exist."""

    def test_start_creates_missing_directory(self, tmp_path):
        target = tmp_path / "reservations_dir_that_does_not_exist_yet"
        assert not target.exists()
        LocalReservationsStorage(base_path=str(target)).start()
        assert target.is_dir()

    def test_start_is_idempotent_on_existing_directory(self, tmp_path):
        # Pre-create; start() must not fail on an existing dir.
        target = tmp_path / "already_there"
        target.mkdir()
        LocalReservationsStorage(base_path=str(target)).start()
        assert target.is_dir()


class TestLocalReservationsStorageWriteRead:
    """
    End-to-end: write a batch, read one back, verify JSON shape and that
    the caller's agent_spec was not mutated.
    """

    @pytest.mark.asyncio
    async def test_write_then_read_round_trip(self, tmp_path):
        storage = LocalReservationsStorage(base_path=str(tmp_path))
        storage.start()

        reservation = _make_reservation(prefix="rt", lifetime_s=3600.0)
        original_spec = _make_spec()

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

        reservation = _make_reservation(prefix="nomut", lifetime_s=3600.0)
        original_spec = _make_spec()
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

        assert list(tmp_path.iterdir()) == []

    def test_get_missing_reservation_returns_none(self, tmp_path):
        storage = LocalReservationsStorage(base_path=str(tmp_path))
        storage.start()

        got_reservation, got_network = storage.get_one_reservation("nope-does-not-exist")
        assert got_reservation is None
        assert got_network is None


class TestLocalReservationsStorageExpiration:
    """expire_reservations() removes only files whose expiration is in the past."""

    @pytest.mark.asyncio
    async def test_expire_removes_only_stale_files(self, tmp_path):
        storage = LocalReservationsStorage(base_path=str(tmp_path))
        storage.start()

        fresh = _make_reservation(prefix="fresh", lifetime_s=3600.0,
                                  expires_offset_s=3600.0)   # expires 1h in the future
        stale = _make_reservation(prefix="stale", lifetime_s=60.0,
                                  expires_offset_s=-60.0)    # expired 60s ago

        await storage.add_reservations({fresh: _make_spec(), stale: _make_spec()},
                                       source="unit-test")

        # Sanity: both files present before sweep.
        files_before = sorted(p.name for p in tmp_path.iterdir())
        assert len(files_before) == 2

        storage.expire_reservations()

        files_after = sorted(p.name for p in tmp_path.iterdir())
        assert files_after == [f"{fresh.get_reservation_id()}.json"], (
            f"Expected only the fresh reservation to survive; got {files_after}"
        )

    def test_expire_on_missing_directory_is_no_op(self, tmp_path):
        """
        expire_reservations() called before any writes -- or with the storage
        directory missing -- should log and continue, not raise.
        """
        target = tmp_path / "never_created"
        storage = LocalReservationsStorage(base_path=str(target))
        # NOTE: not calling start() -- directory intentionally doesn't exist.
        storage.expire_reservations()   # must not raise
