
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

from azure.core.exceptions import AzureError


class AzureBlobUtil:
    """Utilities for Azure Blob Storage operations."""

    DEFAULT_RESERVATIONS_PREFIX: str = "reservations/"

    @staticmethod
    def is_retryable_client_error(err: AzureError) -> bool:
        """
        Determine if an AzureError is worth retrying based on error code and HTTP status.

        :param err: The AzureError exception to evaluate
        :return: True if the error is likely transient and worth retrying, False otherwise
        """
        status_code = getattr(err, 'status_code', None)
        error_code = str(getattr(err, 'error_code', '')).lower() if hasattr(err, 'error_code') else ''

        retryable_codes = {
            'serverbisy',
            'operationtimeout',
            'throttlingexception',
            'requesttimeoutexception',
            'internalerror',
            'serviceunavailable',
        }

        if error_code in retryable_codes:
            return True

        if isinstance(status_code, int) and (status_code == 408 or 500 <= status_code < 600):
            return True

        return False

    @staticmethod
    def get_error_code(err: AzureError) -> str:
        """
        Safely extract the error code from an AzureError.

        :param err: The AzureError exception
        :return: The error code as a string, or empty string if not available
        """
        if hasattr(err, 'error_code'):
            code = err.error_code
            return str(code) if code is not None else ""
        return ""
