
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
import json
import os
import shutil
import tempfile

from pathlib import Path

from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Set

from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from neuro_san.interfaces.reservation import Reservation
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.reservations.agent_reservation import AgentReservation
from neuro_san.service.watcher.temp_networks.local.local_reservations_storage import LocalReservationsStorage

from tests.neuro_san.internals.network_providers.byok_agent_spec_builder import ByokAgentSpecBuilder
from tests.neuro_san.service.watcher.temp_networks.local.local_reservations_test_helpers \
    import LocalReservationsTestHelpers


class TestLocalReservationsStorage(IsolatedAsyncioTestCase):
    """
    Unit tests for LocalReservationsStorage.

    Covers the whole class:

      * Constructor validation: the base_path can come from the constructor
        argument or the AGENT_RESERVATIONS_LOCAL_PATH environment variable,
        and missing both raises ValueError.
      * The start() lifecycle: start() creates the storage directory if it
        does not exist and is idempotent against an existing directory.
      * The expire_reservations() sweep: it deletes only files whose
        expiration timestamp is in the past and tolerates a missing storage
        directory (no crash before start()).
      * The write/read round trip: write-then-read of a valid reservation,
        non-mutation of the caller's agent_spec, empty-batch no-op,
        missing-reservation returns (None, None), and the documented
        read-path contract that an already-expired reservation is reported
        as absent.
      * Reading raw specs: the read path resolves each stored agent spec
        through ResolvedNetworkConfigFilter before building the AgentNetwork.
        ExpiringAgentNetworkStorage already resolves specs before writing
        them, but a file written directly (by an older server instance
        during a rolling upgrade, or by other tooling) may still hold a raw
        spec, and get_one_reservation() must hand back the same resolved
        network either way.

    Every test gets its own storage directory from setUp as self.tmp_path;
    the two constructor tests that touch the environment do so inside
    patch.dict(os.environ) so the change is undone even if they fail.
    """

    def setUp(self) -> None:
        """
        Create a fresh temporary directory for the test and register its removal.
        """
        # mkdtemp() rather than TemporaryDirectory(): the directory has to
        # outlive setUp, so there is no with-block to own it (pylint's
        # consider-using-with would flag a bare TemporaryDirectory() here).
        # addCleanup runs even if the test fails or raises.
        tmp_dir: str = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp_dir)
        # LocalReservationsStorage stores os.path.abspath(base_path), which does
        # not resolve symlinks, and the constructor tests compare against the
        # resolved path. On macOS the temp dir lives under a symlink
        # (/var -> /private/var), so resolve() here keeps the expected and
        # actual paths identical; pytest's tmp_path fixture, which these tests
        # used before, hands out an already-resolved path.
        self.tmp_path: Path = Path(tmp_dir).resolve()

    def _list_file_names(self) -> List[str]:
        """
        List the names of the entries currently in the test's storage directory.

        :return: The entry names directly under self.tmp_path, sorted for stable comparison
        """
        names: List[str] = []
        for entry in self.tmp_path.iterdir():
            names.append(entry.name)
        return sorted(names)

    def test_missing_path_raises(self) -> None:
        """No base_path arg and no env var -> ValueError."""
        # patch.dict snapshots os.environ and restores it on exit, which also
        # puts back the key popped here; patch.dict(os.environ, {...}) alone
        # can only add or override keys, not delete one, hence the explicit pop.
        with patch.dict(os.environ):
            os.environ.pop("AGENT_RESERVATIONS_LOCAL_PATH", None)
            with self.assertRaisesRegex(ValueError, "Local path for reservations"):
                LocalReservationsStorage()

    def test_env_var_fallback(self) -> None:
        """base_path defaults from the env var when the arg is empty."""
        with patch.dict(os.environ):
            os.environ["AGENT_RESERVATIONS_LOCAL_PATH"] = str(self.tmp_path)
            storage: LocalReservationsStorage = LocalReservationsStorage()
        self.assertEqual(str(self.tmp_path.resolve()), storage.base_path)

    def test_explicit_arg_wins_over_env(self) -> None:
        """A non-empty base_path arg is used even when the env var is set."""
        with patch.dict(os.environ):
            os.environ["AGENT_RESERVATIONS_LOCAL_PATH"] = "/some/env/path"
            storage: LocalReservationsStorage = LocalReservationsStorage(base_path=str(self.tmp_path))
        self.assertEqual(str(self.tmp_path.resolve()), storage.base_path)

    def test_start_creates_missing_directory(self) -> None:
        """start() creates the base directory when it does not yet exist."""
        target: Path = self.tmp_path / "reservations_dir_that_does_not_exist_yet"
        self.assertFalse(target.exists())
        LocalReservationsStorage(base_path=str(target)).start()
        self.assertTrue(target.is_dir())

    def test_start_is_idempotent_on_existing_directory(self) -> None:
        """start() must not fail when the base directory already exists."""
        target: Path = self.tmp_path / "already_there"
        target.mkdir()
        LocalReservationsStorage(base_path=str(target)).start()
        self.assertTrue(target.is_dir())

    async def test_expire_removes_only_stale_files(self) -> None:
        """expire_reservations() deletes only the reservation files whose deadline has passed."""
        storage: LocalReservationsStorage = LocalReservationsStorage(base_path=str(self.tmp_path))
        storage.start()

        fresh: AgentReservation = LocalReservationsTestHelpers.make_reservation(
            prefix="fresh", lifetime_s=3600.0, expires_offset_s=3600.0)   # +1h
        stale: AgentReservation = LocalReservationsTestHelpers.make_reservation(
            prefix="stale", lifetime_s=60.0, expires_offset_s=-60.0)      # -60s

        await storage.add_reservations(
            {
                fresh: LocalReservationsTestHelpers.make_spec(),
                stale: LocalReservationsTestHelpers.make_spec(),
            },
            source="unit-test",
        )

        # Sanity: both files present before sweep.
        files_before: List[str] = self._list_file_names()
        self.assertEqual(2, len(files_before))

        storage.expire_reservations()

        files_after: List[str] = self._list_file_names()
        self.assertEqual(
            [f"{fresh.get_reservation_id()}.json"], files_after,
            f"Expected only the fresh reservation to survive; got {files_after}",
        )

    def test_expire_on_missing_directory_is_no_op(self) -> None:
        """
        expire_reservations() called before any writes -- or with the storage
        directory missing -- should log and continue, not raise.
        """
        target: Path = self.tmp_path / "never_created"
        storage: LocalReservationsStorage = LocalReservationsStorage(base_path=str(target))
        # NOTE: not calling start() -- directory intentionally doesn't exist.
        storage.expire_reservations()   # must not raise

    async def test_write_then_read_round_trip(self) -> None:
        """Write a reservation, then read it back and verify JSON shape."""
        storage: LocalReservationsStorage = LocalReservationsStorage(base_path=str(self.tmp_path))
        storage.start()

        reservation: AgentReservation = LocalReservationsTestHelpers.make_reservation(
            prefix="rt", lifetime_s=3600.0)
        original_spec: Dict[str, Any] = LocalReservationsTestHelpers.make_spec()

        await storage.add_reservations({reservation: original_spec},
                                       source="unit-test")

        expected_path: Path = self.tmp_path / f"{reservation.get_reservation_id()}.json"
        self.assertTrue(expected_path.is_file())

        # File is valid JSON and has the injected metadata block.
        on_disk: Dict[str, Any] = json.loads(expected_path.read_text(encoding="utf-8"))
        self.assertEqual("n", on_disk["name"])
        self.assertEqual({"model": "gpt"}, on_disk["llm_config"])
        self.assertIn("metadata", on_disk)
        self.assertEqual(reservation.get_reservation_id(), on_disk["metadata"]["reservation"]["id"])
        self.assertIn("stored_at", on_disk["metadata"])

        # get_one_reservation reconstructs a working Reservation + AgentNetwork.
        got_reservation: Optional[Reservation]
        got_network: Optional[AgentNetwork]
        got_reservation, got_network = storage.get_one_reservation(
            reservation.get_reservation_id())
        self.assertIsNotNone(got_reservation)
        self.assertEqual(reservation.get_reservation_id(), got_reservation.get_reservation_id())
        self.assertIsNotNone(got_network)

    async def test_caller_spec_is_not_mutated(self) -> None:
        """
        The storage writes a shallow copy of agent_spec; the caller's original
        dict must remain unchanged so callers can safely reuse templates.
        """
        storage: LocalReservationsStorage = LocalReservationsStorage(base_path=str(self.tmp_path))
        storage.start()

        reservation: AgentReservation = LocalReservationsTestHelpers.make_reservation(
            prefix="nomut", lifetime_s=3600.0)
        original_spec: Dict[str, Any] = LocalReservationsTestHelpers.make_spec()
        keys_before: Set[str] = set(original_spec.keys())

        await storage.add_reservations({reservation: original_spec}, source="unit-test")

        self.assertEqual(
            keys_before, set(original_spec.keys()),
            "add_reservations must not add keys to the caller's agent_spec; "
            f"before={keys_before}, after={set(original_spec.keys())}",
        )

    async def test_empty_batch_is_no_op(self) -> None:
        """add_reservations({}) writes no files and does not raise."""
        storage: LocalReservationsStorage = LocalReservationsStorage(base_path=str(self.tmp_path))
        storage.start()

        await storage.add_reservations({}, source="unit-test")

        self.assertEqual([], list(self.tmp_path.iterdir()))

    def test_get_missing_reservation_returns_none(self) -> None:
        """Reading a non-existent reservation id returns (None, None) rather than raising."""
        storage: LocalReservationsStorage = LocalReservationsStorage(base_path=str(self.tmp_path))
        storage.start()

        got_reservation: Optional[Reservation]
        got_network: Optional[AgentNetwork]
        got_reservation, got_network = storage.get_one_reservation("nope-does-not-exist")
        self.assertIsNone(got_reservation)
        self.assertIsNone(got_network)

    async def test_get_expired_reservation_returns_none(self) -> None:
        """
        get_one_reservation() is documented to return (None, None) for
        already-expired entries. Write a reservation whose deadline is in
        the past, then verify the reader does not surface it -- independent
        of the expiration sweep, which is what removes the on-disk file.

        The file may still exist on disk immediately after the read; only
        expire_reservations() deletes it. The point of this test is the
        read-path contract, not the eventual file cleanup.
        """
        storage: LocalReservationsStorage = LocalReservationsStorage(base_path=str(self.tmp_path))
        storage.start()

        # Deadline 60 seconds in the past.
        stale: AgentReservation = LocalReservationsTestHelpers.make_reservation(
            prefix="stale-read", lifetime_s=60.0, expires_offset_s=-60.0)
        await storage.add_reservations(
            {stale: LocalReservationsTestHelpers.make_spec()}, source="unit-test")

        # File was written -- read path should NOT surface it as valid.
        self.assertTrue(
            (self.tmp_path / f"{stale.get_reservation_id()}.json").is_file(),
            "Expected the writer to persist the file regardless of expiration; "
            "test setup would be wrong otherwise.",
        )

        got_reservation: Optional[Reservation]
        got_network: Optional[AgentNetwork]
        got_reservation, got_network = storage.get_one_reservation(
            stale.get_reservation_id())
        self.assertIsNone(
            got_reservation,
            "get_one_reservation() must not return an expired reservation; "
            "got a non-None reservation from a file with deadline in the past.",
        )
        self.assertIsNone(got_network)

    async def test_get_one_reservation_resolves_raw_spec(self) -> None:
        """
        A raw spec written straight to disk comes back with the global sly_data_schema
        merged into the front man, while the file itself is left exactly as written.
        """
        base_path: str = str(self.tmp_path)
        storage: LocalReservationsStorage = LocalReservationsStorage(base_path=base_path)
        storage.start()
        reservation: AgentReservation = LocalReservationsTestHelpers.make_reservation(prefix="raw",
                                                                                      lifetime_s=3600.0)
        reservation_id: str = reservation.get_reservation_id()
        # Write through the storage directly, bypassing ExpiringAgentNetworkStorage,
        # the way a pre-filtering server instance would have.
        await storage.add_reservations({reservation: ByokAgentSpecBuilder.make_spec(reservation_id)},
                                       source="unit-test")

        # Guard against a vacuous pass: the on-disk spec really is unresolved.
        path: str = os.path.join(base_path, f"{reservation_id}.json")
        with open(path, "r", encoding="utf-8") as file_handle:
            on_disk: Dict[str, Any] = json.load(file_handle)
        self.assertNotIn("sly_data_schema", on_disk["tools"][0]["function"])

        got_reservation: Optional[Reservation]
        got_network: Optional[AgentNetwork]
        got_reservation, got_network = storage.get_one_reservation(reservation_id)

        # Reading resolves in memory only; the file is left exactly as written.
        with open(path, "r", encoding="utf-8") as file_handle:
            after_read: Dict[str, Any] = json.load(file_handle)
        self.assertEqual(on_disk, after_read)

        self.assertIsNotNone(got_reservation)
        self.assertIsInstance(got_network, AgentNetwork)
        front_man_spec: Dict[str, Any] = ByokAgentSpecBuilder.front_man_spec(got_network)
        self.assertEqual(["llm_config"], front_man_spec["function"]["sly_data_schema"]["required"])
        self.assertIn("fallbacks", front_man_spec["llm_config"])

    async def test_get_one_reservation_strips_legacy_commondefs(self) -> None:
        """
        A raw spec on disk that still carries a commondefs block (written by an older
        instance) has the substitution applied and the block dropped when read, exactly
        as the write side does now, so every instance serves the same network.
        """
        storage: LocalReservationsStorage = LocalReservationsStorage(base_path=str(self.tmp_path))
        storage.start()
        reservation: AgentReservation = LocalReservationsTestHelpers.make_reservation(prefix="legacy",
                                                                                      lifetime_s=3600.0)
        reservation_id: str = reservation.get_reservation_id()
        agent_spec: Dict[str, Any] = ByokAgentSpecBuilder.make_spec(reservation_id)
        agent_spec["commondefs"] = {"replacement_strings": {"greet": "hello"}}
        agent_spec["tools"][0]["instructions"] = "{greet}"
        await storage.add_reservations({reservation: agent_spec}, source="unit-test")

        got_network: Optional[AgentNetwork]
        _, got_network = storage.get_one_reservation(reservation_id)

        self.assertIsInstance(got_network, AgentNetwork)
        self.assertEqual("hello", ByokAgentSpecBuilder.front_man_spec(got_network)["instructions"])
        self.assertNotIn("commondefs", got_network.get_config())
