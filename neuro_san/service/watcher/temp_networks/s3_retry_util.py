
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

from random import random
from time import sleep as sync_sleep

from logging import getLogger
from logging import Logger

from botocore.exceptions import BotoCoreError
from botocore.exceptions import ClientError

from leaf_common.logging.sensitive_logger import SensitiveLogger


class S3RetryUtil:
    """
    Utilities for retrying AWS S3 operations.
    """

    @staticmethod
    def is_retryable_client_error(err: ClientError) -> bool:
        """
        Determine if a ClientError is worth retrying based on its error code and HTTP status.
        :param err: The ClientError exception to evaluate
        :return: True if the error is likely transient and worth retrying, False otherwise
        """
        client_error = err.response.get("Error")
        if not client_error:
            client_error = {}
        code = client_error.get("Code", "")
        error_response = err.response.get("ResponseMetadata")
        if not error_response:
            error_response = {}
        status = error_response.get("HTTPStatusCode", 0)

        # Common codes for transient situations
        retryable_codes = {
            "SlowDown",
            "Throttling",
            "ThrottlingException",
            "RequestTimeout",
            "RequestTimeoutException",
            "InternalError",
            "ServiceUnavailable",
            "503",
        }
        if code in retryable_codes:
            return True
        # Retry on some 5xx
        if isinstance(status, int) and 500 <= status < 600:
            return True
        return False

    @staticmethod
    def do_with_retries(source: str, fn, *, max_attempts: int = 8, base_sleep: float = 0.25):
        """
        Generic retry wrapper for boto3 calls.
        boto3/botocore already retries, but this adds a bit of extra resilience and backoff for batch operations.
        """
        logger: Logger = getLogger(__name__)
        sensitive_logger: SensitiveLogger = SensitiveLogger(logger)
        sleep: float = 0.0
        attempt: int = 1
        while True:
            try:
                return fn()
            except ClientError as err:
                if attempt >= max_attempts or not S3RetryUtil.is_retryable_client_error(err):
                    raise
                sleep = S3RetryUtil.exponential_backoff_with_jitter(base_sleep, attempt)
                sensitive_logger.warning("%s: Retryable sync ClientError (%s). attempt=%d", source, err, attempt)
                sync_sleep(sleep)
                attempt += 1
            except BotoCoreError as err:
                # Often transient network/serialization issues
                if attempt >= max_attempts:
                    raise
                sleep = S3RetryUtil.exponential_backoff_with_jitter(base_sleep, attempt)
                sensitive_logger.warning("%s: Retryable sync BotoCoreError (%s). attempt=%d", source, err, attempt)
                sync_sleep(sleep)
                attempt += 1
            except Exception as err:  # pylint: disable=broad-except
                # Catch-all for unexpected exceptions; log and re-raise
                sensitive_logger.error("%s: Unexpected sync error (%s). attempt=%d", source, err, attempt)
                raise

    @staticmethod
    def exponential_backoff_with_jitter(base_sleep: float, attempt: int) -> float:
        """
        Compute exponential backoff with jitter
        :param base_sleep: base sleep time
        :param attempt: attempt number
        :return: sleep time as float
        """
        sleep: float = base_sleep * (2 ** (attempt - 1))
        sleep = sleep * (0.5 + random())  # sleep time jitter
        return sleep

    @staticmethod
    def get_obj_key_for_reservation(prefix: str, reservation_id: str) -> str:
        """
        Helper method to construct the S3 object key for a given reservation ID.
        :param prefix: The path prefix in the S3 bucket
        :param reservation_id: The ID of the reservation
        :return: The corresponding S3 object key
        """
        return f"{prefix}{reservation_id}.json"
