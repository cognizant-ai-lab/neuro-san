
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
from json import loads

from typing import Any
from typing import Dict
from typing import List

from neuro_san.internals.graph.filters.network_config_filter_chain import NetworkConfigFilterChain

from tests.neuro_san.service.watcher.temp_networks.s3.s3_reservations_storage_test_base \
    import S3ReservationsStorageTestBase


class TestS3ReservationsStorage(S3ReservationsStorageTestBase):
    """
    Unit tests for S3ReservationsStorage as a facade: every test here writes
    through add_reservations and reads back through get_one_reservation
    against the in-memory fake S3 client that S3ReservationsStorageTestBase
    wires up.

    add_reservations / get_one_reservation / expire_reservations are one-line
    delegations to the writer, reader and expiration components, so the
    write-only, read-only and sweep behaviours are pinned in
    test_s3_reservations_writer.py, test_s3_reservations_reader.py and
    test_s3_reservations_expiration.py. What belongs here is the contract
    the two sides have to agree on end to end: a reservation and its agent
    spec survive the round trip equivalently, N entries in one batch read
    back independently, a repeated id is last-writer-wins, the metadata
    block is initialized when absent and merged (not replaced) when the
    caller authored one.
    """

    async def test_add_then_get_returns_equivalent_reservation(self) -> None:
        """
        Round-trip a single reservation through S3ReservationsStorage: the
        reservation feature works end-to-end against an S3-like backend, in
        that writing a reservation and reading it back yields an equivalent
        Reservation and an AgentNetwork carrying the original agent spec.

        Uses a reservation id and an authored network name that are
        deliberately different strings so each assertion below exercises
        a distinct code path (storage-assigned registry name vs
        JSON-persisted spec name).
        """
        # Reservation id mimics the production "<prefix>-<uuid4>" shape
        # (see AgentReservation.get_reservation_id), but uses a stable,
        # easily grep-able placeholder in place of a real UUID so the
        # test is deterministic. Format breakdown:
        #   "copy_cat"   <- prefix; the agent network name being reserved
        #   "-"          <- separator inserted by AgentReservation
        #   "test-UUID-0001"
        #                <- where a real uuid4() string would normally
        #                   appear; "test-UUID" is an obvious test marker
        #                   so any leaked value is identifiable as a
        #                   fixture, and "0001" lets multi-reservation
        #                   tests append "0002", "0003", etc.
        reservation_id = "copy_cat-test-UUID-0001"
        # Bare network name as it would appear in a HOCON registry entry,
        # distinct from the reservation id.
        agent_spec_name = "copy_cat"
        reservation = self._make_reservation(reservation_id, lifetime_seconds=1234.5)
        agent_spec = self._make_agent_spec(agent_spec_name)

        # Write
        await self.storage.add_reservations({reservation: agent_spec})

        # Read. Capture the lookup id in its own variable so the assertion
        # messages below always reflect the exact value passed to
        # get_one_reservation, even if a future maintainer mutates the call
        # for a sanity check.
        lookup_id = reservation_id
        returned_reservation, returned_network = \
            self.storage.get_one_reservation(lookup_id)

        # Reservation came back with all the fields intact.
        self.assertIsNotNone(
            returned_reservation,
            f"get_one_reservation({lookup_id!r}) returned None for the "
            "reservation that was just written via add_reservations(); the "
            "write/read round-trip is broken.",
        )
        self.assertEqual(
            reservation.get_reservation_id(),
            returned_reservation.get_reservation_id(),
            "Reservation id changed after S3 round-trip.",
        )
        self.assertEqual(
            reservation.get_lifetime_in_seconds(),
            returned_reservation.get_lifetime_in_seconds(),
            "Reservation lifetime_in_seconds changed after S3 round-trip.",
        )
        self.assertEqual(
            reservation.get_expiration_time_in_seconds(),
            returned_reservation.get_expiration_time_in_seconds(),
            "Reservation expiration_time_in_seconds changed after S3 round-trip.",
        )

        # Agent network came back and carries the original spec under the
        # reservation id used as its name.
        self.assertIsNotNone(
            returned_network,
            f"get_one_reservation({lookup_id!r}) returned a None "
            "AgentNetwork; the agent spec stored alongside the reservation "
            "could not be reconstructed from S3.",
        )
        self.assertEqual(
            reservation_id,
            returned_network.name,
            "Returned AgentNetwork.name does not match the reservation id used "
            "as its registry name.",
        )
        self.assertEqual(
            agent_spec_name,
            returned_network.get_config().get("name"),
            "Original agent_spec['name'] was not preserved through S3 round-trip.",
        )
        # The reader resolves the spec through ResolvedNetworkConfigFilter before building the
        # AgentNetwork (see S3ReservationsReader.get_one_reservation), so the tools come back
        # with the top-level defaults applied - here the network-level llm_config copied onto
        # the front man. Compare against the resolved form of what was written, which is what
        # any client of the storage is meant to receive. The bare chain is enough to build
        # that expectation because only "tools" is compared and the filter's extra step (dropping
        # a top-level commondefs block) does not touch it.
        resolved_spec: Dict[str, Any] = NetworkConfigFilterChain().filter_config(agent_spec)
        self.assertEqual(
            resolved_spec.get("tools"),
            returned_network.get_config().get("tools"),
            "Original agent_spec['tools'] was not preserved (in resolved form) through S3 round-trip.",
        )
        self.assertEqual(
            agent_spec.get("llm_config"),
            returned_network.get_config().get("llm_config"),
            "Original agent_spec['llm_config'] was not preserved through "
            "S3 round-trip.",
        )

    async def test_add_writes_each_reservation_independently(self) -> None:
        """
        S3ReservationsStorage.add_reservations accepts a dict of multiple
        {Reservation: agent_spec} pairs; this exercises the for-loop that
        iterates over those pairs. A single add_reservations call with N>1
        entries writes one S3 object per entry and preserves each spec
        independently. The other round-trip tests in this class only
        exercise N=1 per call, so the for-loop body is never iterated more
        than once there. This test fills that gap.

        One call to add_reservations({r1: s1, r2: s2, r3: s3}) writes
        three distinct S3 objects, one per reservation, each with the
        spec it was paired with. No cross-contamination between
        iterations of the for-loop in add_reservations.
        """
        # Three reservation ids; -0001 .. -0004 are reserved by earlier
        # tests. Use -0005a/b/c so the suffix unambiguously belongs to
        # this test if a future bug leaves orphans behind.
        res_a = self._make_reservation("copy_cat-test-UUID-0005a", lifetime_seconds=600.0)
        res_b = self._make_reservation("copy_cat-test-UUID-0005b", lifetime_seconds=1200.0)
        res_c = self._make_reservation("copy_cat-test-UUID-0005c", lifetime_seconds=1800.0)

        # Each spec carries a distinct model_name so we can prove later
        # that each id reads back with its own spec, not a sibling's.
        spec_a = self._make_agent_spec("copy_cat")
        spec_a["llm_config"]["model_name"] = "gpt-4o"
        spec_b = self._make_agent_spec("copy_cat")
        spec_b["llm_config"]["model_name"] = "claude-3-5-sonnet"
        spec_c = self._make_agent_spec("copy_cat")
        spec_c["llm_config"]["model_name"] = "gemini-2.0-flash"

        # Single batch call - the entire interaction with the storage.
        await self.storage.add_reservations(
            {res_a: spec_a, res_b: spec_b, res_c: spec_c}
        )

        # All three S3 objects exist, each at its own documented key.
        # Catches off-by-one bugs (only first/last entry written) and
        # any iteration that skips entries (e.g., stride bug).
        expected_keys = {
            f"reservations/{res_a.get_reservation_id()}.json",
            f"reservations/{res_b.get_reservation_id()}.json",
            f"reservations/{res_c.get_reservation_id()}.json",
        }
        self.assertEqual(
            expected_keys,
            set(self.fake_s3.objects),
            f"Expected three distinct S3 keys, got "
            f"{list(self.fake_s3.objects)}",
        )

        # Each reservation reads back with its OWN model_name. Catches
        # cross-contamination bugs where one iteration of the for-loop
        # leaks state into the next (e.g., metadata accumulating across
        # entries because the input dict reference is shared).
        _, network_a = self.storage.get_one_reservation(res_a.get_reservation_id())
        _, network_b = self.storage.get_one_reservation(res_b.get_reservation_id())
        _, network_c = self.storage.get_one_reservation(res_c.get_reservation_id())

        self.assertEqual(
            "gpt-4o",
            network_a.get_config()["llm_config"]["model_name"],
            "Spec for res_a did not survive the batch write; was "
            "overwritten or cross-contaminated by another iteration.",
        )
        self.assertEqual(
            "claude-3-5-sonnet",
            network_b.get_config()["llm_config"]["model_name"],
            "Spec for res_b did not survive the batch write; was "
            "overwritten or cross-contaminated by another iteration.",
        )
        self.assertEqual(
            "gemini-2.0-flash",
            network_c.get_config()["llm_config"]["model_name"],
            "Spec for res_c did not survive the batch write; was "
            "overwritten or cross-contaminated by another iteration.",
        )

    async def test_add_reservations_overwrites_on_duplicate_id(self) -> None:
        """
        S3ReservationsStorage.add_reservations is last-writer-wins for a given
        reservation id: a second call writes a new JSON blob to the same S3 key,
        replacing the first one.

        The storage uses plain put_object with no conditional header, so S3's
        default "second write wins" semantics apply. This is intentional: it
        lets callers refresh a reservation's expiration or swap the agent_spec
        by re-issuing add_reservations under the same id.

        Catches a future regression that "protects" against duplicate ids by
        skipping the second put or by merging old and new payloads instead of
        replacing.

        Write twice under the same reservation id with different lifetimes
        and different agent specs; verify the second write fully replaces
        the first.
        """
        # Single reservation id reused across both writes.
        reservation_id = "copy_cat-test-UUID-0003"

        # First write: short lease, original model.
        first_reservation = self._make_reservation(
            reservation_id, lifetime_seconds=60.0,
        )
        first_spec = self._make_agent_spec("copy_cat")
        first_spec["llm_config"]["model_name"] = "gpt-4o"
        await self.storage.add_reservations({first_reservation: first_spec})

        # Second write: same id, longer lease, different model.
        second_reservation = self._make_reservation(
            reservation_id, lifetime_seconds=7200.0,
        )
        second_spec = self._make_agent_spec("copy_cat")
        second_spec["llm_config"]["model_name"] = "gpt-5.2"
        await self.storage.add_reservations({second_reservation: second_spec})

        # Read back; the storage should expose only the second write.
        returned_reservation, returned_network = \
            self.storage.get_one_reservation(reservation_id)

        # Reservation reflects the second write's lease.
        self.assertEqual(
            7200.0,
            returned_reservation.get_lifetime_in_seconds(),
            "lifetime_in_seconds reflects the first write; the second "
            "add_reservations call did not overwrite the S3 object.",
        )
        self.assertEqual(
            second_reservation.get_expiration_time_in_seconds(),
            returned_reservation.get_expiration_time_in_seconds(),
            "expiration_time_in_seconds does not match the second write.",
        )

        # Agent spec reflects the second write's content.
        self.assertEqual(
            "gpt-5.2",
            returned_network.get_config().get("llm_config").get("model_name"),
            "llm_config.model_name reflects the first write; the second "
            "add_reservations call did not overwrite the S3 object.",
        )

        # Exactly one S3 object exists for this id - the storage didn't
        # leak a second blob under a different key, and didn't merge the
        # two payloads. Goes through the FakeS3Client's in-memory dict
        # because we own that layer in this test.
        matching_keys: List[str] = []
        for key in self.fake_s3.objects:
            if key.endswith(f"{reservation_id}.json"):
                matching_keys.append(key)
        self.assertEqual(
            1,
            len(matching_keys),
            f"Expected exactly one S3 object for {reservation_id}, found "
            f"{len(matching_keys)}: {matching_keys}",
        )

    async def test_add_initializes_metadata_when_spec_lacks_key(self) -> None:
        """
        The "metadata" key on an agent_spec is documented as optional in the
        project's HOCON registry files (see registries/*.hocon: "Optional
        metadata describing this agent network"). Callers may legitimately
        hand a metadata-less spec to add_reservations. The storage's read
        path requires metadata.reservation on every stored object, so the
        write path must initialize the field when missing - otherwise
        downstream reads would crash.

        This exercises the storage's defensive init branch:
            if agent_spec.get("metadata") is None:
                agent_spec["metadata"] = {}
            agent_spec["metadata"].update(new_metadata)

        The other tests in this suite all pass agent_specs that include a
        pre-populated "metadata" key (built by _make_agent_spec). This
        test exercises the other side of the storage's metadata-init
        branch: input specs that arrive without a "metadata" key.

        When the input agent_spec has no "metadata" key,
        add_reservations should:
          - Not raise (the is-None guard fires before .update).
          - Write exactly one S3 object.
          - Persist the storage-injected reservation+stored_at fields
            inside metadata so the read path can reconstruct the
            reservation.

        Catches a regression where the is-None guard is dropped
        (KeyError on .update), where init creates the wrong shape, or
        where init silently no-ops the write entirely.
        """
        reservation_id = "copy_cat-test-UUID-0011"
        reservation = self._make_reservation(reservation_id, lifetime_seconds=600.0)

        # Build an agent_spec with NO "metadata" key. This shape
        # mirrors a fresh registry entry whose "Optional metadata"
        # field was left out.
        spec_without_metadata = {
            "name": "copy_cat",
            "llm_config": {"model_name": "gpt-5.2"},
            "tools": [
                {
                    "name": "copy_cat",
                    "function": {
                        "description": "Frontman that delegates to the copyist.",
                    },
                    "instructions": "Always call the copyist tool.",
                    "tools": ["copyist"],
                }
            ],
        }

        # Precondition: the input genuinely has no metadata key.
        # If this fails, the test isn't exercising the branch we
        # think it is.
        self.assertNotIn(
            "metadata",
            spec_without_metadata,
            "Precondition violated: spec_without_metadata unexpectedly "
            "has a 'metadata' key.",
        )

        # The call should NOT raise. If it does, the is-None guard
        # has been removed and KeyError fires on .update().
        await self.storage.add_reservations({reservation: spec_without_metadata})

        # Exactly one S3 object was written. Catches a regression
        # where the missing-metadata path silently no-ops the write.
        self.assertEqual(
            1,
            len(self.fake_s3.objects),
            f"Expected exactly one S3 object after writing a spec "
            f"without metadata; bucket has {list(self.fake_s3.objects)}.",
        )

        # The reservation round-trips via the public read API. This
        # is the end-to-end check that the storage-injected metadata
        # was written correctly enough for the read path to find it.
        result_reservation, result_network = self.storage.get_one_reservation(
            reservation_id
        )
        self.assertIsNotNone(
            result_reservation,
            f"get_one_reservation returned None for {reservation_id!r} "
            f"after writing a spec without metadata; the storage's "
            f"metadata initialization did not produce a readable object.",
        )
        self.assertEqual(
            reservation_id,
            result_reservation.get_reservation_id(),
            "Read-back reservation id does not match the written id.",
        )
        self.assertIsNotNone(
            result_network,
            f"get_one_reservation returned None for the network for "
            f"{reservation_id!r}; the agent_spec round-trip is broken.",
        )

        # On-disk JSON has the storage-injected fields under metadata,
        # confirming the init branch produced the right shape (not
        # just an empty stub or a shape the read path tolerates by
        # accident).
        body = self.fake_s3.objects[f"reservations/{reservation_id}.json"]
        parsed = loads(body.decode("utf-8"))
        self.assertIn(
            "metadata",
            parsed,
            f"On-disk JSON has no 'metadata' key after the init branch "
            f"fired; got top-level keys: {list(parsed)}.",
        )
        self.assertIn(
            "reservation",
            parsed["metadata"],
            f"On-disk metadata is missing the storage-injected "
            f"'reservation' field; got metadata keys: "
            f"{list(parsed['metadata'])}.",
        )
        self.assertEqual(
            reservation_id,
            parsed["metadata"]["reservation"]["id"],
            "On-disk metadata.reservation.id does not match the "
            "written reservation id.",
        )

    async def test_add_does_not_clobber_user_authored_metadata(self) -> None:
        """
        S3ReservationsStorage.add_reservations must merge into agent_spec["metadata"]
        rather than replace it, so user-authored keys (description, tags, etc.)
        survive the round-trip.

        Real registry entries (e.g. neuro_san/registries/copy_cat.hocon) ship
        with their own metadata.description and metadata.tags. The storage
        must preserve those keys when injecting its own reservation/stored_at.

        When the input agent_spec already has a user-authored 'metadata'
        dict, add_reservations must merge its own 'reservation' and
        'stored_at' entries into that dict rather than replacing it. After
        the round-trip, the user keys must still be present alongside the
        storage-injected keys.

        Regression guard: a future change that did
            agent_spec["metadata"] = new_metadata
        instead of
            agent_spec["metadata"].update(new_metadata)
        would silently drop user-authored metadata in production.
        """
        # New reservation id (the round-trip test reserved -0001).
        reservation_id = "copy_cat-test-UUID-0002"
        agent_spec_name = "copy_cat"
        reservation = self._make_reservation(reservation_id, lifetime_seconds=600.0)
        agent_spec = self._make_agent_spec(agent_spec_name)
        # Pre-populate metadata as a real registry entry would, mirroring
        # neuro_san/registries/copy_cat.hocon. Capturing the values up front
        # so the assertions below compare against the originals (and so a
        # future maintainer can't accidentally read the post-merge dict by
        # going through the same agent_spec reference).
        original_description = (
            "Simple agent network demonstrating use of temporary agent "
            "networks using Reservations."
        )
        original_tags = ["example", "reservations"]
        agent_spec["metadata"] = {
            "description": original_description,
            "tags": original_tags,
        }

        # Write
        await self.storage.add_reservations({reservation: agent_spec})

        # Read
        _, returned_network = self.storage.get_one_reservation(reservation_id)
        returned_metadata: Dict[str, Any] = \
            returned_network.get_config().get("metadata")

        self.assertIsNotNone(
            returned_metadata,
            "metadata block missing from the agent spec returned by "
            "get_one_reservation; the storage's metadata injection wiped "
            "the dict instead of merging into it.",
        )

        # User-authored keys survived the merge.
        self.assertEqual(
            original_description,
            returned_metadata.get("description"),
            "User-authored metadata['description'] was clobbered by the "
            "storage's metadata injection.",
        )
        self.assertEqual(
            original_tags,
            returned_metadata.get("tags"),
            "User-authored metadata['tags'] was clobbered by the storage's "
            "metadata injection.",
        )

        # Storage-injected keys are present alongside the user keys.
        self.assertIn(
            "reservation",
            returned_metadata,
            "Storage-injected metadata['reservation'] is missing after "
            "S3 round-trip; add_reservations did not record the reservation "
            "block on the agent spec.",
        )
        self.assertEqual(
            reservation_id,
            returned_metadata["reservation"].get("id"),
            "metadata['reservation']['id'] does not match the reservation "
            "id that was written.",
        )
        self.assertIn(
            "stored_at",
            returned_metadata,
            "Storage-injected metadata['stored_at'] is missing after S3 "
            "round-trip.",
        )
        self.assertIsInstance(
            returned_metadata["stored_at"],
            float,
            "metadata['stored_at'] is not a float Unix timestamp; the "
            "storage stamped a non-numeric value.",
        )
