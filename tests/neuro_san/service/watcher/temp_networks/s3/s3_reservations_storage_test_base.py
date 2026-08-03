
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
import os
import time

from typing import Any
from typing import Dict

from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from aiobotocore.credentials import AioCredentials
from botocore.credentials import Credentials

from neuro_san.internals.reservations.agent_reservation import AgentReservation
from neuro_san.service.watcher.temp_networks.s3.s3_reservations_storage import S3ReservationsStorage
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
            "neuro_san.service.watcher.temp_networks.s3.aws_sync_client_worker.Session.create_client",
            return_value=self.fake_s3,
        )
        boto3_patcher.start()
        # Restores the real boto3_client symbol after the test completes,
        # regardless of pass/fail.
        self.addCleanup(boto3_patcher.stop)

        # Patch Session.get_credentials at the import boundary in s3_reservations_writer
        # so storage.start() receives deterministic fake credentials.
        def _fake_get_credentials(*_args, **_kwargs):
            return Credentials("bogus", "bogus")

        credentials_patcher = patch(
            "neuro_san.service.watcher.temp_networks.s3.aws_sync_client_worker.Session.get_credentials",
            new=_fake_get_credentials,
        )
        credentials_patcher.start()
        # Restores the real AioSession symbol after the test completes, regardless of pass/fail.
        self.addCleanup(credentials_patcher.stop)

        self.fake_async_s3: FakeAsyncS3Client = FakeAsyncS3Client(self.fake_s3)

        # Patch aiobotocore_client at the import boundary in s3_reservations_storage
        # so storage.start() receives our fake instead of a real aiobotocore client.
        aiobotocore_patcher = patch(
            "neuro_san.service.watcher.temp_networks.s3.aws_async_client_worker.AioSession.create_client",
            return_value=self.fake_async_s3,
        )
        aiobotocore_patcher.start()
        # Restores the real aiobotocore symbol after the test completes,
        # regardless of pass/fail.
        self.addCleanup(aiobotocore_patcher.stop)

        # Patch AioSession.get_credentials at the import boundary in s3_reservations_writer
        # so storage.start() receives deterministic fake credentials.
        async def _async_fake_get_credentials(*_args, **_kwargs):
            return AioCredentials("bogus", "bogus")

        credentials_patcher = patch(
            "neuro_san.service.watcher.temp_networks.s3.aws_async_client_worker.AioSession.get_credentials",
            new=_async_fake_get_credentials,
        )
        credentials_patcher.start()
        # Restores the real AioSession symbol after the test completes, regardless of pass/fail.
        self.addCleanup(credentials_patcher.stop)

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
