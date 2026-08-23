
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
from typing import Optional
from typing import Tuple

from asyncio import get_running_loop
from asyncio import run
from logging import getLogger
from logging import Logger

from neuro_san.interfaces.reservation import Reservation
from neuro_san.internals.network_providers.abstract_reservations_storage import AbstractReservationsStorage
from neuro_san.service.watcher.temp_networks.azure.azure_blob_reservations_expiration \
    import AzureBlobReservationsExpiration
from neuro_san.service.watcher.temp_networks.azure.azure_blob_reservations_reader import AzureBlobReservationsReader
from neuro_san.service.watcher.temp_networks.azure.azure_blob_reservations_writer import AzureBlobReservationsWriter
from neuro_san.service.watcher.temp_networks.azure.azure_blob_util import AzureBlobUtil
from neuro_san.service.watcher.temp_networks.common.external_storage_util import ExternalStorageUtil


class AzureBlobReservationsStorage(AbstractReservationsStorage):
    """
    Azure Blob Storage-based implementation of ReservationsStorage.

    Stores reservations as JSON objects in an Azure Blob container, with each reservation
    stored as a separate blob using ETag-based optimistic concurrency control.

    Architecture:
    - One blob per reservation (no shared index) avoids global lock contention
    - Concurrent writes use ETag optimistic concurrency, not locks
    - Expiration scanning is disabled by default (expensive at scale)
    """

    def __init__(self, container_name: str = "", prefix: str = AzureBlobUtil.DEFAULT_RESERVATIONS_PREFIX,
                 check_expirations_interval_seconds: float = 0.0):
        """
        Initialize Azure Blob Reservations Storage.

        :param container_name: Azure Blob container name (defaults to AGENT_RESERVATIONS_AZURE_CONTAINER env var)
        :param prefix: Blob key prefix for reservation objects
        :param check_expirations_interval_seconds: How often to check for expired reservations.
                                    If 0 or negative, expiration checks are disabled.
        """
        super().__init__(
            storage_name="azure_blob_storage",
            check_expirations_interval_seconds=check_expirations_interval_seconds
        )
        self.logger: Logger = getLogger(self.__class__.__name__)

        self.writer = AzureBlobReservationsWriter(container_name=container_name, prefix=prefix)
        self.reader = AzureBlobReservationsReader(container_name=container_name, prefix=prefix)
        self.expiration = AzureBlobReservationsExpiration(container_name=container_name, prefix=prefix)

    def start(self):
        """
        Initialize Azure Blob Storage client and validate connection to container.
        """
        # This can throw ValueError if env var is invalid
        self._check_interval_seconds = ExternalStorageUtil.get_check_interval_seconds(self.logger)

        self.reader.start()
        self.expiration.start()

        self.logger.info("Azure Blob Reservations Storage initialized")
        super().start()

    async def add_reservations(self, reservations_dict: Dict[Reservation, Any], source: str = None):
        """
        Add/update reservations in Azure Blob Storage.

        :param reservations_dict: Dictionary mapping Reservation objects to their metadata
        :param source: Source identifier for logging
        """
        if not reservations_dict:
            return

        await self.writer.add_reservations(reservations_dict, source)

    def get_one_reservation(self, obj_key: str) -> Tuple[Reservation, Any]:
        """
        Retrieve a single reservation from Azure Blob Storage.

        :param obj_key: The reservation ID
        :return: Tuple of (Reservation, metadata) or (None, None) if not found or expired
        """
        reservation, metadata = self.reader.get_one_reservation(obj_key)
        return reservation, metadata

    def expire_reservations(self):
        """
        Scan and delete expired reservations from Azure Blob Storage.

        Note: This is expensive at scale. Default CHECK_PERIOD is 0 (disabled).
        Consider using Azure Blob lifecycle policies or index-tag-based expiry instead.
        """
        self.expiration.expire_reservations()

    def stop(self, timeout: Optional[float] = None):
        """Close connections to Azure Blob Storage."""
        super().stop(timeout)
        try:
            if self.writer:
                try:
                    loop = get_running_loop()
                except RuntimeError:
                    loop = None

                if loop:
                    # DEF - we should use the AsyncioExecutor to create the task
                    loop.create_task(self.writer.close())
                else:
                    run(self.writer.close())
        except Exception as err:            # pylint: disable=broad-except
            self.logger.warning("Error closing writer: %s", str(err))

        try:
            if self.reader:
                self.reader.close()
        except Exception as err:            # pylint: disable=broad-except
            self.logger.warning("Error closing reader: %s", str(err))

        try:
            if self.expiration:
                self.expiration.close()
        except Exception as err:            # pylint: disable=broad-except
            self.logger.warning("Error closing expiration: %s", str(err))
