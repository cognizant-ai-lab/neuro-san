
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
from typing import Optional
from typing import Type

from time import time
from json import loads
from json.decoder import JSONDecodeError
from logging import getLogger
from logging import Logger
from os import getenv

from leaf_common.resolution.resolver_util import ResolverUtil

# Lazily resolve here because this is one of the first places the import happens
AzureError: Type[Any] = ResolverUtil.create_type("azure.core.exceptions.AzureError",
                                                 install_if_missing="azure-core")
DefaultAzureCredential: Type[Any] = ResolverUtil.create_type("azure.identity.DefaultAzureCredential",
                                                             install_if_missing="azure-identity")
ContainerClient: Type[Any] = ResolverUtil.create_type("azure.storage.blob.ContainerClient",
                                                      install_if_missing="azure-storage-blob")

from neuro_san.service.watcher.temp_networks.azure.azure_blob_util import AzureBlobUtil     # noqa: E402


class AzureBlobReservationsExpiration:
    """
    Handles expiration of reservations in Azure Blob Storage.
    Scans the container for expired reservations and deletes them.
    """

    def __init__(self, container_name: str = "", prefix: str = AzureBlobUtil.DEFAULT_RESERVATIONS_PREFIX):
        """
        Initialize Azure Blob Reservations Expiration handler.

        :param container_name: Azure Blob container name
        :param prefix: Blob key prefix for reservation objects
        """
        self.logger: Logger = getLogger(self.__class__.__name__)

        env_container: str = getenv("AGENT_RESERVATIONS_AZURE_CONTAINER", "")
        self.container_name: str = container_name or env_container
        if not self.container_name:
            raise ValueError(
                "Azure Blob container name must be provided via container_name parameter or "
                "AGENT_RESERVATIONS_AZURE_CONTAINER environment variable"
            )

        self.prefix: str = prefix
        self.container_client: Optional[ContainerClient] = None

    def _get_container_client(self) -> ContainerClient:
        """Get or create a sync container client."""
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

    def expire_reservations(self):
        """
        Scan all reservation blobs and delete expired ones.

        WARNING: This operation lists and downloads metadata for ALL reservation blobs,
        which can be expensive at scale. Consider using Azure Blob lifecycle policies
        or index-tag-based deletion instead. Default CHECK_PERIOD is 0 (disabled).
        """
        container = self._get_container_client()
        current_time = time()
        blobs_to_delete = []

        try:
            for blob_props in container.list_blobs(name_starts_with=self.prefix):
                blob_name = blob_props.name
                try:
                    blob_client = container.get_blob_client(blob_name)
                    blob_data = blob_client.download_blob()
                    blob_content = blob_data.readall()

                    json_data = loads(blob_content.decode('utf-8'))
                    if isinstance(json_data, dict):
                        metadata = json_data.get("metadata", {})
                        expiration_time = metadata.get("expiration_time_in_seconds", 0)

                        if current_time > expiration_time > 0:
                            blobs_to_delete.append(blob_name)

                except (JSONDecodeError, ValueError, AzureError) as err:
                    self.logger.warning("Error processing blob %s during expiration: %s", blob_name, str(err))

            if blobs_to_delete:
                for i in range(0, len(blobs_to_delete), 256):
                    batch = blobs_to_delete[i:i + 256]
                    try:
                        container.delete_blobs(*batch)
                        self.logger.debug("Deleted %d expired reservation blobs", len(batch))
                    except AzureError as err:
                        self.logger.error("Error deleting expired blobs: %s", str(err))

        except AzureError as err:
            self.logger.error("Error listing blobs during expiration scan: %s", str(err))

    def start(self):
        """Initialize the expiration handler and validate connection."""
        try:
            container = self._get_container_client()
            container.get_container_properties()
            self.logger.info("Expiration handler initialized for container: %s", self.container_name)
        except AzureError as err:
            self.logger.error("Failed to connect to Azure Blob container %s: %s", self.container_name, str(err))
            raise

    def close(self):
        """Close the container client."""
        if self.container_client:
            self.container_client.close()
            self.container_client = None
