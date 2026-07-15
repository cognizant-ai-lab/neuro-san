
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
from typing import Callable

from time import sleep as sync_sleep
from time import perf_counter

from logging import getLogger
from logging import Logger
from threading import Lock as SyncLock

from botocore.client import BaseClient
from botocore.credentials import Credentials
from botocore.credentials import ReadOnlyCredentials
from botocore.exceptions import BotoCoreError
from botocore.exceptions import ClientError
from botocore.session import get_session
from botocore.session import Session

from leaf_common.logging.sensitive_logger import SensitiveLogger
from leaf_common.parsers.dictionary_extractor import DictionaryExtractor

from neuro_san.service.watcher.temp_networks.s3_util import S3Util


# pylint: disable=too-many-instance-attributes
class AwsSyncClientWorker:
    """
    Class that manages a particular AWS boto synchronous work_function (from functools.partial)
    that has sync_aws_client as an argument whose credentials are properly handled for
    short-lived synchronous boto clients.
    """

    def __init__(self, name: str, aws_service: str = "s3"):
        """
        Constructor

        :param name: Name for logging as to whose behalf this class is operating.
        :param aws_service: Name of the AWS service to initialize the boto client
        """
        self.name: str = name
        self.aws_service: str = aws_service
        self.logger: Logger = getLogger(self.__class__.__name__)

        self.sync_aws_client_lock: SyncLock = SyncLock()

        # Boto Machinations
        # We should be able to have a single Session for the lifetime of this object
        self.session: Session = None

        # Cached frozen credentials which can be invalidated should they expire
        self.frozen_credentials: ReadOnlyCredentials = None

    def retry_with_new_client(self, work_function: Callable, *, source: str = None) -> Any:
        """
        Retries the work_function when client credentials can expire.
        :param work_function: The work function to retry
        :param *: extra keyword arguments for work_function
        :param source: A string describing where the deployment was coming from
        :return: What work_function returns
        """

        max_attempts: int = 8
        last_err: Exception = None

        for attempt in range(1, max_attempts + 1):
            try:
                retval: Any = self.do_work_with_new_client(work_function, attempt=attempt)
                return retval

            except ClientError as err:
                extractor = DictionaryExtractor(err.response)
                if "ExpiredToken" not in extractor.get("Error.Code", ""):
                    raise

                last_err = err

                # Background: Certain IAM Instance Roles, ECS Task Roles or AWS SSO/IAM Identity Center
                #             profiles have token-based credentials that may expire.
                #             See: https://docs.aws.amazon.com/boto3/latest/guide/configuration.html

                # Reset the cached credentials as they are likely expired and try again.
                self.frozen_credentials = None
                if source is None:
                    source = self.name
                self.logger.warning("%s (%d): %s credentials seem to have expired. Retrying. "
                                    "If you believe you have non-expiring %s credentials, be sure they are correct.",
                                    source, attempt, self.aws_service, self.aws_service)

        # Exhausted retries
        if last_err is not None:
            raise last_err

        raise RuntimeError(f"{self.aws_service} credential retries exhausted without capturing an error") from last_err

    def do_work_with_new_client(self, work_function: Callable, *, attempt: int = 1) -> Any:
        """
        This method separates the machinations of obtaining a proper S3 client
        from add_all_reservations() which does all the actual work.

        :param work_function: The work function to retry
        :param *: extra keyword arguments for work_function
        :param attempt: Attempt number
        :return: What work_function returns
        """

        retval: Any = None

        # Create an botocore client for sync operations.
        sync_aws_client: BaseClient = None

        lock_released: bool = False
        acquired_lock: bool = False

        start_time: float = perf_counter()
        lock_aquired_time: float = 0.0
        client_created_time: float = 0.0
        lock_released_time: float = 0.0
        try:
            # Serialize creation of the Client with the lock to avoid credential-chain races.
            # pylint: disable=consider-using-with
            self.sync_aws_client_lock.acquire()
            lock_aquired_time = perf_counter()
            acquired_lock = True

            # Get the current notion of frozen credentials.
            frozen_creds: ReadOnlyCredentials = self.get_frozen_credentials()
            sync_aws_client = self.session.create_client(
                self.aws_service,
                aws_access_key_id=frozen_creds.access_key,
                aws_secret_access_key=frozen_creds.secret_key,
                aws_session_token=frozen_creds.token,
            )
            client_created_time = perf_counter()

            # Normally this is done in a python ContextManager using a with-statement,
            # but we want to be holding the lock while we create the client to avoid
            # credential-chain races like NoCredentialsError.

            # Release the lock while we process, allowing other tasks to work on
            # getting their own sync_aws_client.
            self.sync_aws_client_lock.release()
            lock_released_time = perf_counter()
            lock_released = True

            retval = work_function(sync_aws_client=sync_aws_client)

        finally:
            # Always release the lock if we successfully acquired it and have not already done so,
            # in case there was an error getting/entering the context manager.
            if acquired_lock and not lock_released:
                self.sync_aws_client_lock.release()

            if sync_aws_client is not None:
                sync_aws_client.close()

        finish_time: float = perf_counter()
        self.logger.info("%s (%d): Lock acquisition in: %fs. Client context creation after: %fs. "
                         "Lock release after: %fs. Finish after: %fs",
                         self.name, attempt,
                         lock_aquired_time - start_time,
                         client_created_time - start_time,
                         lock_released_time - start_time,
                         finish_time - start_time)
        return retval

    def get_frozen_credentials(self) -> ReadOnlyCredentials:
        """
        Get the frozen credentials for the current session.
        We are assuming that we already have the sync_aws_client_lock.
        """

        # Use a local copy to avoid a race with the ClientError retry block
        local_frozen: ReadOnlyCredentials = self.frozen_credentials

        # If we already have some credentials, use them
        if local_frozen is not None:
            return local_frozen

        # Create the session if needed
        # We should only need one for the lifetime of the object
        if self.session is None:
            self.session = get_session()

        credentials: Credentials = self.session.get_credentials()

        # Avoid a small race condition with the ClientError retry block
        # by always returning a local copy
        local_frozen = credentials.get_frozen_credentials()
        self.frozen_credentials = local_frozen

        return local_frozen

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
                if attempt >= max_attempts or not S3Util.is_retryable_client_error(err):
                    raise

                sleep = S3Util.exponential_backoff_with_jitter(base_sleep, attempt)
                sensitive_logger.warning("%s: Retryable sync ClientError (%s). attempt=%d", source, err, attempt)
                sync_sleep(sleep)
                attempt += 1
            except BotoCoreError as err:
                # Often transient network/serialization issues
                if attempt >= max_attempts:
                    raise

                sleep = S3Util.exponential_backoff_with_jitter(base_sleep, attempt)
                sensitive_logger.warning("%s: Retryable sync BotoCoreError (%s). attempt=%d", source, err, attempt)
                sync_sleep(sleep)
                attempt += 1
            except Exception as err:  # pylint: disable=broad-except
                # Catch-all for unexpected exceptions; log and re-raise
                sensitive_logger.error("%s: Unexpected sync error (%s). attempt=%d", source, err, attempt)
                raise
