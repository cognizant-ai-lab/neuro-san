
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

from typing import Optional, Tuple

from json import loads
from json.decoder import JSONDecodeError
from logging import getLogger, Logger

from neuro_san.interfaces.reservation import Reservation
from neuro_san.service.watcher.temp_networks.azure.azure_blob_util import AzureBlobUtil
from neuro_san.service.watcher.temp_networks.azure_blob_reservations_retriever import AzureBlobReservationsRetriever


class AzureBlobReservationsReader:
    """
    Azure Blob Storage-based reader for reservation objects.
    Handles retrieval and deserialization of reservations from blob storage.
    """

    def __init__(self, container_name: str = "", prefix: str = AzureBlobUtil.DEFAULT_RESERVATIONS_PREFIX):
        """
        Initialize Azure Blob Reservations Reader.

        :param container_name: Azure Blob container name
        :param prefix: Blob key prefix for reservation objects
        """
        self.logger: Logger = getLogger(self.__class__.__name__)
        self.prefix: str = prefix
        self.retriever = AzureBlobReservationsRetriever(container_name=container_name, prefix=prefix)

    def get_one_reservation(self, obj_key: str) -> Tuple[Optional[Reservation], Optional[dict]]:
        """
        Retrieve a single reservation from blob storage.

        :param obj_key: The reservation ID (blob key)
        :return: Tuple of (Reservation, metadata_dict) or (None, None) if not found or expired
        """
        blob_name = f"{self.prefix}{obj_key}.json"

        try:
            blob_content = self.retriever.retrieve_blob(blob_name)
            if blob_content is None:
                return None, None

            json_data = loads(blob_content.decode('utf-8'))

            if not isinstance(json_data, dict):
                self.logger.warning("Malformed reservation blob %s: expected dict, got %s", blob_name, type(json_data))
                return None, None

            reservation_dict = json_data
            metadata = reservation_dict.get("metadata", {})

            reservation = Reservation(
                id=metadata.get("reservation_id", obj_key),
                lifetime_in_seconds=metadata.get("lifetime_in_seconds", 0),
                expiration_time_in_seconds=metadata.get("expiration_time_in_seconds", 0)
            )

            return reservation, metadata

        except JSONDecodeError as err:
            self.logger.warning("Failed to parse JSON from blob %s: %s", blob_name, str(err))
            return None, None
        except Exception as err:
            self.logger.error("Error reading reservation blob %s: %s", blob_name, str(err))
            return None, None

    def start(self):
        """Initialize the reader and validate blob storage connection."""
        self.retriever.start()

    def close(self):
        """Close the reader."""
        self.retriever.close()
