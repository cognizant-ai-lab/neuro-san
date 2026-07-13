
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
from typing import Awaitable

from asyncio import Lock as AsyncLock
from time import perf_counter

from logging import getLogger
from logging import Logger
from threading import Lock as SyncLock

from aiobotocore.client import AioBaseClient
from aiobotocore.session import get_session
from aiobotocore.session import AioSession
from aiobotocore.session import ClientCreatorContext

from botocore.credentials import Credentials
from botocore.credentials import ReadOnlyCredentials
from botocore.exceptions import ClientError

from leaf_common.parsers.dictionary_extractor import DictionaryExtractor


# pylint: disable=too-many-instance-attributes
class S3AsyncClientWorker:
    """
    AWS S3-based class that manages a particular async work_function (from functools.partial)
    that has async_s3_client as an argument whose credentials are properly handled for
    short-lived async S3 clients.
    """

    def __init__(self, name: str):
        """
        Initialize S3 reservations storage.

        :param name: Name for logging as to whose behalf this class is operating.
        """
        self.name: str = name
        self.logger: Logger = getLogger(self.__class__.__name__)

        self.sync_lock: SyncLock = SyncLock()
        self.async_s3_client_lock: AsyncLock = None

        # Boto Machinations
        # We should be able to have a single Session for the lifetime of this object
        self.session: AioSession = None

        # Cached frozen credentials which can be invalidated should they expire
        self.frozen_credentials: ReadOnlyCredentials = None

    async def retry_with_new_client(self, work_function: Awaitable, *, source: str = None) -> Any:
        """
        Retries the async work_function when client credentials can expire.
        :param work_function: The async work function to retry
        :param *: extra keyword arguments for work_function
        :param source: A string describing where the deployment was coming from
        :return: What work_function returns
        """

        # Async lock has to be created in the thread that uses it.
        self.ensure_async_lock_exists()

        max_attempts: int = 8
        last_err: Exception = None

        for attempt in range(1, max_attempts + 1):
            try:
                retval: Any = await self.do_work_with_new_client(work_function, attempt=attempt)
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
                self.logger.warning(
                    "%s (%d): S3 credentials seem to have expired. Retrying. "
                    "If you believe you have non-expiring S3 credentials, be sure they are correct.",
                    source,
                    attempt,
                )

        # Exhausted retries
        if last_err is not None:
            raise last_err

        raise RuntimeError("S3 credential retries exhausted without capturing an error") from last_err

    async def do_work_with_new_client(self, work_function: Awaitable, *, attempt: int = 1) -> Any:
        """
        This method separates the machinations of obtaining a proper S3 client
        from add_all_reservations() which does all the actual work.

        :param work_function: The async work function to retry
        :param *: extra keyword arguments for work_function
        :param attempt: Attempt number
        :return: What work_function returns
        """

        retval: Any = None

        # Create an aiobotocore client for async operations.
        async_s3_client: AioBaseClient = None

        async_s3_client_creator_context: ClientCreatorContext = None
        lock_released: bool = False
        acquired_lock: bool = False

        start_time: float = perf_counter()
        lock_aquired_time: float = 0.0
        client_created_time: float = 0.0
        lock_released_time: float = 0.0
        try:
            # Serialize creation of the ClientCreatorContext with the lock to avoid credential-chain races.
            await self.async_s3_client_lock.acquire()
            lock_aquired_time = perf_counter()
            acquired_lock = True

            # Get the current notion of frozen credentials.
            frozen_creds: ReadOnlyCredentials = await self.get_frozen_credentials()
            async_s3_client_creator_context = self.session.create_client(
                "s3",
                aws_access_key_id=frozen_creds.access_key,
                aws_secret_access_key=frozen_creds.secret_key,
                aws_session_token=frozen_creds.token,
            )
            client_created_time = perf_counter()

            # Normally this is done in a python ContextManager using a with-statement,
            # but we want to be holding the lock while we create the client to avoid
            # credential-chain races like NoCredentialsError.

            async with async_s3_client_creator_context as async_s3_client:

                # Release the lock while we process, allowing other tasks to work on
                # getting their own async_s3_client. (Not an async method)
                self.async_s3_client_lock.release()
                lock_released_time = perf_counter()
                lock_released = True

                retval = await work_function(async_s3_client=async_s3_client)

        finally:
            # Always release the lock if we successfully acquired it and have not already done so,
            # in case there was an error getting/entering the context manager.
            if acquired_lock and not lock_released:
                self.async_s3_client_lock.release()

        finish_time: float = perf_counter()
        self.logger.info("%s (%d): Lock acquisition in: %fs. Client context creation after: %fs. "
                         "Lock release after: %fs. Finish after: %fs",
                         self.name, attempt,
                         lock_aquired_time - start_time,
                         client_created_time - start_time,
                         lock_released_time - start_time,
                         finish_time - start_time)
        return retval

    def ensure_async_lock_exists(self):
        """
        Be sure we have an asyncio Lock to get our sessions.
        """
        # Note that none of this is async in and of itself.
        if self.async_s3_client_lock is None:
            with self.sync_lock:
                # Be sure everyone has the same lock
                if self.async_s3_client_lock is None:
                    self.async_s3_client_lock = AsyncLock()

    async def get_frozen_credentials(self) -> ReadOnlyCredentials:
        """
        Get the frozen credentials for the current session.
        We are assuming that we already have the async_s3_client_lock.
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

        credentials: Credentials = await self.session.get_credentials()

        # Avoid a small race condition with the ClientError retry block
        # by always returning a local copy
        local_frozen = await credentials.get_frozen_credentials()
        self.frozen_credentials = local_frozen

        return local_frozen
