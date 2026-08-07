
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
from typing import Tuple

from logging import getLogger
from logging import Logger

from neuro_san.interfaces.reservation import Reservation
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.network_providers.abstract_reservations_storage import AbstractReservationsStorage
from neuro_san.service.watcher.temp_networks.common.external_storage_util import ExternalStorageUtil
from neuro_san.service.watcher.temp_networks.s3.s3_reservations_expiration import S3ReservationsExpiration
from neuro_san.service.watcher.temp_networks.s3.s3_reservations_reader import S3ReservationsReader
from neuro_san.service.watcher.temp_networks.s3.s3_reservations_writer import S3ReservationsWriter
from neuro_san.service.watcher.temp_networks.s3.s3_util import S3Util


class S3ReservationsStorage(AbstractReservationsStorage):
    """
    AWS S3-based implementation of ReservationsStorage.

    Stores reservations as JSON objects in an S3 bucket, with each reservation
    stored in its associated agent spec as metadata.
    """

    def __init__(self, bucket_name: str = "", prefix: str = S3Util.DEFAULT_RESERVATIONS_PREFIX,
                 check_expirations_interval_seconds: float = 0.0):
        """
        Initialize S3 reservations storage.

        :param bucket_name: S3 bucket name (defaults to AGENT_RESERVATIONS_S3_BUCKET env var)
        :param prefix: S3 key prefix for reservation objects
        :param check_expirations_interval_seconds: How often to check for expired reservations.
                                    If 0 or negative, expiration checks are disabled.
        """
        # Our default for check_expirations_interval_seconds is 0
        # because S3 expiration check is generally a significant execution load,
        # and we may want to run it externally on demand rather than on a fixed schedule inside the service.
        super().__init__(storage_name="s3_storage",
                         check_expirations_interval_seconds=check_expirations_interval_seconds)
        self.logger: Logger = getLogger(self.__class__.__name__)

        self.writer = S3ReservationsWriter(bucket_name=bucket_name, prefix=prefix)
        self.reader = S3ReservationsReader(bucket_name=bucket_name, prefix=prefix)
        self.expiration = S3ReservationsExpiration(bucket_name=bucket_name, prefix=prefix)

        # This can throw ValueError if env var is invalid
        self._check_interval_seconds = ExternalStorageUtil.get_check_interval_seconds(self.logger)

    def start(self):
        """
        Validate connection to the bucket, creating each worker's long-lived
        S3 client on first use.

        Calling this again only re-validates bucket access through those same
        clients; it does not rebuild them or re-resolve credentials (that
        happens in AwsSyncClientWorker.reset_client(), driven by its
        credential retry).
        """
        self.reader.start()
        self.expiration.start()

        # We are good with S3 connection and bucket access at this point,
        # let's start underlying logic:
        super().start()

    async def add_reservations(self, reservations_dict: Dict[Reservation, Any], source: str = None):
        """
        Add reservations to S3 storage.

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
        await self.writer.add_reservations(reservations_dict, source)

    def get_one_reservation(self, obj_key: str) -> Tuple[Reservation, AgentNetwork]:
        """
        Sync a single reservation from S3.

        :param obj_key: reservation ID to retrieve (used to construct S3 object key)
        :return: Tuple of (reservation, agent_spec) if successful and not expired,
                 (None, None) otherwise
        """
        reservation_id: str = obj_key
        reservation: Reservation = None
        agent_network: AgentNetwork = None
        reservation, agent_network = self.reader.get_one_reservation(reservation_id)
        return reservation, agent_network

    def expire_reservations(self):
        """
        Remove expired reservations from S3 storage.
        """
        self.expiration.expire_reservations()
