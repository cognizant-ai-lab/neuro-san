
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
import io
import os
import time

from typing import Any
from typing import Dict

from unittest import TestCase
from unittest.mock import patch

from botocore.exceptions import ClientError

from neuro_san.internals.reservations.agent_reservation import AgentReservation
from neuro_san.service.watcher.temp_networks.s3_reservations_storage \
    import S3ReservationsStorage


# pylint: disable=invalid-name,unused-argument
class FakeS3Client:
    """
    Minimal in-memory stand-in for a boto3 S3 client. Only implements the
    methods that S3ReservationsStorage actually calls, storing object bodies
    in a dict keyed by S3 object key. Method signatures use boto3's PascalCase
    keyword arguments so the storage's call sites work unchanged.
    """

    def __init__(self):
        """
        Initialize an empty in-memory bucket.
        """
        self.objects: Dict[str, bytes] = {}

    def head_bucket(self, Bucket: str):
        """
        Stand-in for boto3's head_bucket. Real boto3 returns a response dict
        on success and raises ClientError otherwise. For tests we treat any
        configured bucket as existing.
        """
        return {}

    def put_object(self, Bucket: str, Key: str, Body, ContentType: str):
        """
        Store the given Body bytes (or str, encoded as utf-8) at Key.
        """
        if isinstance(Body, str):
            Body = Body.encode("utf-8")
        self.objects[Key] = Body
        return {}

    def get_object(self, Bucket: str, Key: str):
        """
        Return the stored bytes for Key wrapped in a Body stream, or raise
        a NoSuchKey ClientError if the key is not present.
        """
        if Key not in self.objects:
            raise ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": "Not Found"}},
                "GetObject",
            )
        return {"Body": io.BytesIO(self.objects[Key])}


class TestS3ReservationsStorageRoundTrip(TestCase):
    """
    Exercises the reservation feature through S3ReservationsStorage by
    injecting an in-memory fake S3 client. No real AWS, no LocalStack, no
    extra dependencies.
 
    See S3ReservationsStorage.add_reservations docstring for the on-disk
    JSON schema written to S3.
 
    A subtle point not captured in that schema: AgentNetwork.name is
    assigned in memory at read time (= the lookup id passed to
    get_one_reservation), and is NOT a field in the JSON.
    """

    def setUp(self):
        # Force the env-driven expiration interval to 0 so no background
        # thread is started during tests, regardless of the developer's local
        # environment. clear=False means only this key is overridden; all
        # other env vars are left untouched.
        env_patcher = patch.dict(
            os.environ,
            {"AGENT_RESERVATIONS_EXTERNAL_STORAGE_CHECK_PERIOD_SECONDS": "0"},
            clear=False,
        )
        env_patcher.start()
        # addCleanup runs even if the test fails or raises. patch.dict snapshots
        # the original value of every key it touches before starting, so stop()
        # restores os.environ exactly as it was: a pre-existing value (e.g. "5")
        # is restored to "5", and a previously unset key is removed.
        self.addCleanup(env_patcher.stop)

        self.fake_s3: FakeS3Client = FakeS3Client()

        # Patch boto3_client at the import boundary in s3_reservations_storage
        # so storage.start() receives our fake instead of a real boto3 client.
        boto3_patcher = patch(
            "neuro_san.service.watcher.temp_networks."
            "s3_reservations_storage.boto3_client",
            return_value=self.fake_s3,
        )
        boto3_patcher.start()
        # Restores the real boto3_client symbol after the test completes,
        # regardless of pass/fail.
        self.addCleanup(boto3_patcher.stop)

        self.storage: S3ReservationsStorage = S3ReservationsStorage(
            bucket_name="test-bucket",
            prefix="reservations/",
        )
        self.storage.start()

    @staticmethod
    def _make_reservation(reservation_id: str,
                          lifetime_seconds: float = 3600.0) -> AgentReservation:
        """
        Build an AgentReservation with a deterministic id and a future
        expiration so the reservation is considered active.
        """
        reservation = AgentReservation(
            # Total seconds the reservation is intended to live.
            lifetime_in_seconds=lifetime_seconds,
        )
        # Override AgentReservation's auto-generated uuid4 with a stable
        # test id so the S3 object key is predictable across runs.
        reservation.id = reservation_id
        # Set a future wall-clock deadline so the reservation is considered
        # active (not yet expired) at read time. In production this is
        # done via AgentReservation.set_expiration_from(now, max_lifetime),
        # which clamps lifetime against a server-imposed maximum; the test
        # bypasses the clamp because it isn't under test here.
        reservation.expiration_time_in_seconds = time.time() + lifetime_seconds
        return reservation

    @staticmethod
    def _make_agent_spec(name: str) -> Dict[str, Any]:
        """
        Build an agent spec that mirrors the shape of a real production
        registry entry (see neuro_san/registries/copy_cat.hocon): a top-level
        name, an llm_config, and a non-empty tools list with one frontman-style
        entry. This is enough surface area to verify that arbitrary spec
        fields round-trip through S3 without being silently dropped or
        clobbered by the storage's metadata injection.
        """
        return {
            # The network's authored name (matches the bare "name" field
            # in the registry's HOCON file, e.g. "copy_cat"). Independent
            # of the reservation id used as the S3 object key.
            "name": name,
            # Optional LLM configuration block. Included to verify that
            # arbitrary top-level spec fields (beyond name/tools) survive
            # the S3 round-trip.
            "llm_config": {
                # LLM model identifier the runtime will hand to the client.
                "model_name": "gpt-5.2",
            },
            # List of agent definitions that make up the network. The first
            # entry is the "front man" that talks to the user; subsequent
            # entries are down-chain agents/tools.
            "tools": [
                {
                    # Agent's unique name within this network.
                    "name": name,
                    # OpenAI-style function schema. The "description" also
                    # doubles as the agent's initial system prompt.
                    "function": {
                        "description": "Frontman that delegates to the copyist.",
                    },
                    # Free-form prompt added to the agent's context window.
                    "instructions": "Always call the copyist tool.",
                    # Names of other agents this agent is allowed to invoke.
                    "tools": ["copyist"],
                },
            ],
        }

    def test_add_then_get_returns_equivalent_reservation(self):
        """
        Reservation feature works end-to-end against an S3-like backend:
        writing a reservation and reading it back yields an equivalent
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
        self.storage.add_reservations({reservation: agent_spec})

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
        self.assertEqual(
            agent_spec.get("tools"),
            returned_network.get_config().get("tools"),
            "Original agent_spec['tools'] was not preserved through S3 round-trip.",
        )
        self.assertEqual(
            agent_spec.get("llm_config"),
            returned_network.get_config().get("llm_config"),
            "Original agent_spec['llm_config'] was not preserved through "
            "S3 round-trip.",
        )
