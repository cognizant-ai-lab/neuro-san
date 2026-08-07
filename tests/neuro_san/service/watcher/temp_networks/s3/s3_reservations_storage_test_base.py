
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
Shared scaffolding for S3ReservationsStorage tests.

Pytest's default test-file pattern is test_*.py, so this file (which
does not start with "test_") is not collected as a test module. The
class defined here is imported by sibling test_*.py modules.
"""
import json
import os
import time

from contextlib import contextmanager

from typing import Any
from typing import Dict

from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from botocore.exceptions import ClientError

from neuro_san.internals.reservations.agent_reservation import AgentReservation
from neuro_san.service.watcher.temp_networks.s3.s3_reservations_storage import S3ReservationsStorage
from neuro_san.service.watcher.temp_networks.s3.s3_util import S3Util
from tests.neuro_san.service.watcher.temp_networks.s3.fake_s3_client import FakeS3Client
from tests.neuro_san.service.watcher.temp_networks.s3.fake_async_s3_client import FakeAsyncS3Client


class S3ReservationsStorageTestBase(IsolatedAsyncioTestCase):
    """
    Base TestCase that exercises the reservation feature through
    S3ReservationsStorage by injecting an in-memory FakeS3Client. No real
    AWS, no LocalStack, no extra dependencies.

    Concrete subclasses add focused test_* methods. This class is named so
    that it does NOT begin with "Test" and therefore is not discovered
    directly by pytest; only subclasses with a "Test" prefix run.

    See S3ReservationsStorage.add_reservations docstring for the on-disk
    JSON schema written to S3.

    A subtle point not captured in that schema: AgentNetwork.name is
    assigned in memory at read time (= the lookup id passed to
    get_one_reservation), and is NOT a field in the JSON.
    """

    # S3 key prefix used both to configure the storage under test and by
    # the _put_* helpers below to construct object keys directly.
    PREFIX: str = "reservations/"

    def setUp(self):
        # Force the env-driven expiration interval to 0 so no background
        # thread is started during tests, regardless of the developer's local
        # environment. clear=False means only these keys are overridden; all
        # other env vars are left untouched.
        env_patcher = patch.dict(
            os.environ,
            {
                "AGENT_RESERVATIONS_EXTERNAL_STORAGE_CHECK_PERIOD_SECONDS": "0",
                # Hermeticity barrier: the workers build REAL botocore /
                # aiobotocore sessions (only create_client is patched below),
                # and the sync worker consults the session's credential chain
                # before creating its client. These fake env credentials make
                # that resolution instant and deterministic instead of walking
                # the developer/CI machine's real chain (config files, SSO,
                # IMDS on EC2).
                "AWS_ACCESS_KEY_ID": "testing",
                "AWS_SECRET_ACCESS_KEY": "testing",
                "AWS_SESSION_TOKEN": "testing",
                "AWS_DEFAULT_REGION": "us-east-1",
                "AWS_EC2_METADATA_DISABLED": "true",
            },
            clear=False,
        )
        env_patcher.start()
        # addCleanup runs even if the test fails or raises. patch.dict snapshots
        # the original value of every key it touches before starting, so stop()
        # restores os.environ exactly as it was: a pre-existing value (e.g. "5")
        # is restored to "5", and a previously unset key is removed.
        self.addCleanup(env_patcher.stop)

        self.fake_s3: FakeS3Client = FakeS3Client()

        # Patch Session.create_client at the import boundary in
        # aws_sync_client_worker so the workers receive our fake instead of a
        # real boto3 client. The workers create their clients WITHOUT explicit
        # keys and never consult Session.get_credentials themselves (credential
        # resolution/refresh happens inside real clients at request-signing
        # time), so intercepting create_client is the only seam needed.
        boto3_patcher = patch(
            "neuro_san.service.watcher.temp_networks.s3.aws_sync_client_worker.Session.create_client",
            return_value=self.fake_s3,
        )
        boto3_patcher.start()
        # Restores the real create_client symbol after the test completes,
        # regardless of pass/fail.
        self.addCleanup(boto3_patcher.stop)

        self.fake_async_s3: FakeAsyncS3Client = FakeAsyncS3Client(self.fake_s3)

        # Patch AioSession.create_client at the import boundary in
        # aws_async_client_worker so the writer receives our fake instead of a
        # real aiobotocore client. Same reasoning as the sync patch above: the
        # keyless-client design leaves create_client as the only seam.
        aiobotocore_patcher = patch(
            "neuro_san.service.watcher.temp_networks.s3.aws_async_client_worker.AioSession.create_client",
            return_value=self.fake_async_s3,
        )
        aiobotocore_patcher.start()
        # Restores the real create_client symbol after the test completes,
        # regardless of pass/fail.
        self.addCleanup(aiobotocore_patcher.stop)

        self.storage: S3ReservationsStorage = S3ReservationsStorage(
            bucket_name="test-bucket",
            prefix=self.PREFIX,
        )
        self.storage.start()

    def _put_live_reservation(self, reservation_id: str) -> str:
        """
        Place a well-formed, unexpired reservation object directly into the
        fake bucket (matching the writer's on-disk schema, bypassing the
        writer) so read paths have something real to fetch.

        :return: the reservation id (readers derive the S3 key from it)
        """
        key: str = S3Util.get_obj_key_for_reservation(self.PREFIX, reservation_id)
        self.fake_s3.objects[key] = json.dumps({
            "name": reservation_id,
            "llm_config": {"model_name": "gpt-5.2"},
            "tools": [{"name": reservation_id, "function": {"description": "test frontman"}}],
            "metadata": {
                "reservation": {
                    "id": reservation_id,
                    "lifetime_in_seconds": 3600.0,
                    "expiration_time_in_seconds": time.time() + 3600.0,
                },
                "stored_at": time.time(),
            },
        }).encode("utf-8")
        return reservation_id

    @contextmanager
    def _fresh_reader_client(self, create_client_replacement):
        """
        Re-patch the sync create_client seam with the given replacement and
        discard the reader worker's long-lived client, so that the client
        serving the with-block is provably created by the replacement.
        Without the reset, the reads would keep using the client built in
        this base's setUp (under its own create_client patch) and the
        replacement would never be consulted - making any assertion about
        it vacuous.
        """
        with patch(
            "neuro_san.service.watcher.temp_networks.s3.aws_sync_client_worker.Session.create_client",
            new=create_client_replacement,
        ):
            self.storage.reader.retriever.get_sync_client_worker().reset_client()
            yield

    @staticmethod
    def make_expired_token_error(operation_name: str) -> ClientError:
        """
        Build the ClientError boto3 surfaces when S3 rejects a request that
        was signed with an expired session token (HTTP 400, body code
        "ExpiredToken").

        :param operation_name: The AWS operation name, e.g. "GetObject"
        """
        return ClientError(
            {
                "Error": {
                    "Code": "ExpiredToken",
                    "Message": "The provided token has expired.",
                },
                "ResponseMetadata": {"HTTPStatusCode": 400},
            },
            operation_name,
        )

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
