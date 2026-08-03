
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

from json import dumps
from logging import getLogger
from logging import Logger
from os import getenv
from time import time

from azure.core.exceptions import AzureError
from azure.identity.aio import DefaultAzureCredential
from azure.storage.blob.aio import ContainerClient

# pylint: disable=wrong-import-order
from neuro_san.interfaces.reservation import Reservation
from neuro_san.internals.reservations.reservation_dictionary_converter import ReservationDictionaryConverter
from neuro_san.service.watcher.temp_networks.azure.azure_blob_util import AzureBlobUtil


class AzureBlobReservationsWriter:
    """
    Azure Blob Storage-based class that writes reservations to persistent store.

    Stores reservations as JSON objects in an Azure Blob container, with each reservation
    stored as a separate blob with the format: reservations/<reservation_id>.json
    """

    def __init__(self, name: str = "AzureBlobReservationsWriter",
                 container_name: str = "", prefix: str = AzureBlobUtil.DEFAULT_RESERVATIONS_PREFIX):
        """
        Initialize Azure Blob Reservations Writer.

        :param name: Name of this writer
        :param container_name: Azure Blob container name (defaults to AGENT_RESERVATIONS_AZURE_CONTAINER env var)
        :param prefix: Blob key prefix for reservation objects
        """
        self.name: str = name
        self.logger: Logger = getLogger(self.__class__.__name__)

        env_container: str = getenv("AGENT_RESERVATIONS_AZURE_CONTAINER", "")
        self.container_name: str = container_name or env_container
        if not self.container_name:
            raise ValueError(
                "Azure Blob container name must be provided via container_name parameter or "
                "AGENT_RESERVATIONS_AZURE_CONTAINER environment variable"
            )

        self.prefix: str = prefix
        self.converter = ReservationDictionaryConverter()
        self.container_client: ContainerClient = None

    async def _get_container_client(self) -> ContainerClient:
        """Get or create an async container client."""
        if self.container_client is None:
            connection_string = getenv("AZURE_STORAGE_CONNECTION_STRING", "")
            if connection_string:
                self.container_client = ContainerClient.from_connection_string(
                    connection_string,
                    self.container_name
                )
            else:
                account_url = getenv("AZURE_STORAGE_ACCOUNT_URL", "")
                if not account_url:
                    raise ValueError(
                        "Azure Blob Storage auth requires either "
                        "AZURE_STORAGE_CONNECTION_STRING or AZURE_STORAGE_ACCOUNT_URL"
                    )
                credential = DefaultAzureCredential()
                self.container_client = ContainerClient(account_url, self.container_name, credential)
        return self.container_client

    async def add_reservations(self, reservations_dict: Dict[Reservation, Any], source: str = None):
        """
        Add/update reservations in Azure Blob Storage.

        :param reservations_dict: Dictionary mapping Reservation objects to their metadata
        :param source: Source identifier for logging
        """
        _ = source
        if not reservations_dict:
            return

        container = await self._get_container_client()
        stored_count = 0

        for reservation, reservation_info in reservations_dict.items():
            _ = reservation_info
            blob_name = f"{self.prefix}{reservation.id}.json"

            reservation_dict = self.converter.to_dict(reservation)
            reservation_dict["metadata"] = {
                "reservation_id": reservation.id,
                "lifetime_in_seconds": reservation.lifetime_in_seconds,
                "expiration_time_in_seconds": reservation.expiration_time_in_seconds,
            }
            reservation_dict["stored_at"] = time()

            blob_content = dumps(reservation_dict).encode('utf-8')

            retries = 0
            max_retries = 3
            while retries < max_retries:
                try:
                    await container.upload_blob(blob_name, blob_content, overwrite=True)
                    stored_count += 1
                    break
                except AzureError as err:
                    if AzureBlobUtil.is_retryable_client_error(err) and retries < max_retries - 1:
                        retries += 1
                        self.logger.warning(
                            "Transient error uploading %s, retry %d/%d: %s",
                            blob_name, retries, max_retries, str(err)
                        )
                    else:
                        self.logger.error("Failed to upload reservation blob %s: %s", blob_name, str(err))
                        raise

        self.logger.debug("Stored %d reservations in Azure Blob Storage", stored_count)

    async def close(self):
        """Close the container client."""
        if self.container_client:
            await self.container_client.close()
            self.container_client = None
