
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

from typing import Optional

from os import getenv
from logging import getLogger, Logger

from azure.storage.blob import ContainerClient
from azure.core.exceptions import ResourceNotFoundError, AzureError

from neuro_san.service.watcher.temp_networks.azure_blob_util import AzureBlobUtil


class AzureBlobReservationsRetriever:
    """
    Helper class for retrieving individual reservation blobs from Azure.
    Handles synchronous blob retrieval with retry logic and error handling.
    """

    def __init__(self, container_name: str = "", prefix: str = AzureBlobUtil.DEFAULT_RESERVATIONS_PREFIX):
        """
        Initialize Azure Blob Reservations Retriever.

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
                from azure.identity import DefaultAzureCredential  # pylint: disable=import-outside-toplevel
                account_url = getenv("AZURE_STORAGE_ACCOUNT_URL", "")
                if not account_url:
                    raise ValueError(
                        "Azure Blob Storage auth requires either "
                        "AZURE_STORAGE_CONNECTION_STRING or AZURE_STORAGE_ACCOUNT_URL"
                    )
                credential = DefaultAzureCredential()
                self.container_client = ContainerClient(account_url, self.container_name, credential)
        return self.container_client

    def retrieve_blob(self, blob_name: str) -> Optional[bytes]:
        """
        Retrieve a blob's content from Azure Storage.

        :param blob_name: Name of the blob to retrieve
        :return: Blob content as bytes, or None if not found
        """
        container = self._get_container_client()

        retries = 0
        max_retries = 3
        while retries < max_retries:
            try:
                blob_client = container.get_blob_client(blob_name)
                blob_data = blob_client.download_blob()
                return blob_data.readall()
            except ResourceNotFoundError:
                return None
            except AzureError as err:
                if AzureBlobUtil.is_retryable_client_error(err) and retries < max_retries - 1:
                    retries += 1
                    self.logger.warning(
                        "Transient error retrieving %s, retry %d/%d: %s",
                        blob_name, retries, max_retries, str(err)
                    )
                else:
                    self.logger.error("Failed to retrieve blob %s: %s", blob_name, str(err))
                    return None

        # All retries were exhausted on transient errors without returning.
        return None

    def start(self):
        """Initialize the container client and validate connection."""
        try:
            container = self._get_container_client()
            container.get_container_properties()
            self.logger.info("Successfully connected to Azure Blob container: %s", self.container_name)
        except AzureError as err:
            self.logger.error("Failed to connect to Azure Blob container %s: %s", self.container_name, str(err))
            raise

    def close(self):
        """Close the container client."""
        if self.container_client:
            self.container_client.close()
            self.container_client = None
