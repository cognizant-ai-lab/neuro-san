
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

from typing import Any
from typing import Dict

from asyncio import Lock as AsyncLock
from os import getenv
from time import perf_counter
from time import time
from functools import partial

from json import dumps
from logging import getLogger
from logging import Logger
from threading import Lock as SyncLock

from aiobotocore.client import AioBaseClient
from aiobotocore.session import get_session
from aiobotocore.session import AioSession
from aiobotocore.session import ClientCreatorContext

from neuro_san.interfaces.reservation import Reservation
from neuro_san.internals.reservations.reservation_dictionary_converter import ReservationDictionaryConverter
from neuro_san.service.watcher.temp_networks.s3_retry_util import S3RetryUtil


class S3ReservationsWriter:
    """
    AWS S3-based class that writes reservations out to persistent store
    managed by S3ReservationsStorage.

    Stores reservations as JSON objects in an S3 bucket, with each reservation
    stored in its associated agent spec as metadata.

    The main entry point here is add_reservations(), which eventually gets called from the
    TempNetworkStorageUpdater.process_one_queued_item() method via the
    AbstractAgentReservationist.deploy_together() method.
    These calls happen from their own asyncio EventLoop, very separate from the reads and expirations
    also managed by S3ReservationsStorage.
    """

    def __init__(self, name: str = "S3ReservationsWriter", bucket_name: str = "", prefix: str = "reservations/"):
        """
        Initialize S3 reservations storage.

        :param bucket_name: S3 bucket name (defaults to AGENT_RESERVATIONS_S3_BUCKET env var)
        :param prefix: S3 key prefix for reservation objects
        """
        self.name: str = name
        self.logger: Logger = getLogger(self.__class__.__name__)

        # Configure bucket name from parameter or environment variable
        env_bucket: str = getenv("AGENT_RESERVATIONS_S3_BUCKET", "")
        self.bucket_name: str = bucket_name or env_bucket
        if not self.bucket_name:
            raise ValueError(
                "S3 bucket name must be provided via bucket_name parameter or "
                "AGENT_RESERVATIONS_S3_BUCKET environment variable"
            )

        # Set up S3 key prefix and initialize sync target
        self.prefix: str = prefix

        self.sync_lock: SyncLock = SyncLock()
        self.async_s3_client_lock: AsyncLock = None

        self.converter = ReservationDictionaryConverter()

    async def add_reservations(self, reservations_dict: Dict[Reservation, Any],
                               source: str = None):
        """
        Add reservations to S3 storage.
        Main entry point.

        On-disk JSON schema written per reservation
        (key = "<prefix><reservation_id>.json"):

            {
                "name":       <str>,    # Authored network name (HOCON "name")
                "llm_config": <dict>,   # Optional LLM settings
                "tools":      <list>,   # Agent definitions making up the network
                ...                     # Any other top-level spec fields
                "metadata": {
                    ...                                          # User-authored keys (merged in)
                    "reservation": {                    # Injected by this method
                        "id":                          <str>,    # "<prefix>-<uuid4>"
                        "lifetime_in_seconds":         <float>,  # Lease duration
                        "expiration_time_in_seconds":  <float>,  # Wall-clock deadline
                    },
                    "stored_at": <float>,                        # time.time() at write
                }
            }

        Notes:
          * User-authored metadata keys (e.g. "description", "tags") are
            preserved; this method merges into agent_spec["metadata"]
            rather than replacing it.
          * lifetime_in_seconds:        client-requested duration.
          * expiration_time_in_seconds: now + min(lifetime, server max);
                                        Unix timestamp the system enforces against.
          * stored_at:                  time.time() at write; useful for
                                        clock-skew audit and orphan detection.

        :param reservations_dict: A mapping of Reservation -> some deployable agent spec
        :param source: A string describing where the deployment was coming from
        """
        self.logger.info("%s: Adding %d reservations to S3", self.name, len(reservations_dict))
        if len(reservations_dict) == 0:
            return

        self.ensure_asnync_lock_exists()

        # Create an aiobotocore client for async operations.
        async_s3_client: AioBaseClient = None

        async_s3_client_creator_context: ClientCreatorContext = None
        lock_released: bool = False
        acquired_lock: bool = False

        start_time: float = perf_counter()
        lock_aquired_time: float = 0.0
        session_created_time: float = 0.0
        lock_released_time: float = 0.0
        try:
            # Serialize creation of the ClientCreatorContext with the lock to avoid credential-chain races.
            await self.async_s3_client_lock.acquire()
            lock_aquired_time = perf_counter()
            acquired_lock = True

            # Note: We can probably do better than doing this block every single time.
            #       Many articles hint at frozen-credentials caching, but that will require
            #       an extra layer of retry complexity at this level.
            session: AioSession = get_session()
            async_s3_client_creator_context = session.create_client("s3")
            session_created_time = perf_counter()

            # Normally this is done in a python ContextManager using a with-statement,
            # but we want to be holding the lock while we create the client to avoid
            # credential-chain races like NoCredentialsError.

            async with async_s3_client_creator_context as async_s3_client:

                # Release the lock while we process, allowing other tasks to work on
                # getting their own async_s3_client. (Not an async method)
                self.async_s3_client_lock.release()
                lock_released_time = perf_counter()
                lock_released = True

                await self.add_all_reservations(async_s3_client, reservations_dict, source)

        finally:
            # Always release the lock if we successfully acquired it and have not already done so,
            # in case there was an error getting/entering the context manager.
            if acquired_lock and not lock_released:
                self.async_s3_client_lock.release()

        finish_time: float = perf_counter()

        self.logger.info("Lock acquisition in: %fs. Session creation after: %fs. "
                         "Lock release after: %fs. Finish after: %fs",
                         lock_aquired_time - start_time,
                         session_created_time - start_time,
                         lock_released_time - start_time,
                         finish_time - start_time)

    def ensure_asnync_lock_exists(self):
        """
        Be sure we have an asyncio Lock to get our sessions.
        """
        if self.async_s3_client_lock is None:
            with self.sync_lock:
                # Be sure everyone has the same lock
                if self.async_s3_client_lock is None:
                    self.async_s3_client_lock = AsyncLock()

    async def add_all_reservations(self, async_s3_client: AioBaseClient,
                                   reservations_dict: Dict[Reservation, Dict[str, Any]],
                                   source: str = None):
        """
        Add all reservations to S3 storage.
        :param async_s3_client: An aiobotocore S3 client to use for the put_object call
        :param reservations_dict: A mapping of Reservation -> some deployable agent spec
        :param source: A string describing where the deployment was coming from
        """
        # Process each reservation/agent spec pair individually
        reservation: Reservation = None
        agent_spec: Dict[str, Any] = None
        for reservation, agent_spec in reservations_dict.items():
            await self.add_one_reservation(async_s3_client, reservation, agent_spec, source)

    async def add_one_reservation(self, async_s3_client: AioBaseClient,
                                  reservation: Reservation,
                                  agent_spec: Dict[str, Any],
                                  source: str = None):
        """
        Add a single reservation to S3 storage.
        :param async_s3_client: An aiobotocore S3 client to use for the put_object call
        :param reservation: The reservation to add
        :param agent_spec: The agent spec to add
        :param source: A string describing where the deployment was coming from
        """
        # Build complete data structure containing reservation metadata,
        # the associated agent_spec, source information, and storage timestamp
        current_time: float = time()
        new_metadata: Dict[str, Any] = {
            "reservation": self.converter.to_dict(reservation),  # Serialized reservation object
            "stored_at": current_time              # When stored in S3
        }
        if agent_spec.get("metadata") is None:
            agent_spec["metadata"] = {}
        agent_spec["metadata"].update(new_metadata)

        # Generate S3 key using prefix and reservation ID for easy lookup
        reservation_id: str = reservation.get_reservation_id()
        key: str = S3RetryUtil.get_obj_key_for_reservation(self.prefix, reservation_id)

        # Store as JSON object in S3 with proper content type
        json_body: str = dumps(agent_spec, indent=4)  # Pretty-printed JSON

        put_function = partial(async_s3_client.put_object,
                               Bucket=self.bucket_name,
                               Key=key,
                               Body=json_body,
                               ContentType="application/json")

        if source is None:
            source = self.name
        await S3RetryUtil.async_do_with_retries(source, put_function)

        self.logger.debug("%s: Successfully stored reservation %s in S3", self.name, reservation_id)
