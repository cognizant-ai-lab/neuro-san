
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

from asyncio import CancelledError
from asyncio import Lock as AsyncLock
from asyncio import sleep as async_sleep
from time import perf_counter

from logging import getLogger
from logging import Logger
from threading import Lock as SyncLock

from aiobotocore.client import AioBaseClient
from aiobotocore.session import get_session
from aiobotocore.session import AioSession
from aiobotocore.session import ClientCreatorContext

from botocore.exceptions import BotoCoreError
from botocore.exceptions import ClientError
from botocore.exceptions import NoCredentialsError

from leaf_common.logging.sensitive_logger import SensitiveLogger

from neuro_san.service.watcher.temp_networks.s3_util import S3Util

# Module-level so do_with_retries() below does not construct them per call:
# logging.getLogger() takes the process-global logging lock on every
# invocation, and do_with_retries() runs once per put_object.
_LOGGER: Logger = getLogger(__name__)
_SENSITIVE_LOGGER: SensitiveLogger = SensitiveLogger(_LOGGER)


class AwsAsyncClientWorker:
    """
    Class that manages a particular AWS boto async work_function (from functools.partial)
    that has async_aws_client as an argument, supplying it with an aiobotocore
    client created per call.

    Credential handling is delegated to aiobotocore by creating the client
    WITHOUT explicit keys: such a client holds the session's credential
    OBJECT and freezes it per request at signing time. For token-based
    credential sources (IAM Instance Role, ECS Task Role, AWS SSO/IAM
    Identity Center) that object is refreshable, checks its expiry window on
    every request, and refreshes itself BEFORE signing - so the client never
    presents an expired token to S3. The previous design passed a frozen
    key/secret/token snapshot to create_client(), which pins static
    credentials with no refresh machinery. See issue #1153.

    Unlike AwsSyncClientWorker (whose client serves the per-request read hot
    path and is therefore long-lived), this worker still creates its client
    per work_function call: aiobotocore clients are async context managers
    whose lifetime must be managed inside the event loop that uses them, the
    writer that owns this worker has no stop() hook at which a long-lived
    context could be exited cleanly, and the write path runs per deployment
    batch - not per request - so client construction is not a hot-path cost
    here.
    """

    # Credential-retry policy for retry_with_new_client(): enough attempts,
    # with short jittered backoff between them, to ride out a several-second
    # external rotation window (a credentials file being rewritten) without
    # stalling the write queue for tens of seconds. Backoff matters because
    # each attempt re-resolves the full credential chain (possibly network
    # calls to IMDS/ECS/SSO).
    CREDENTIAL_RETRY_MAX_ATTEMPTS: int = 4
    CREDENTIAL_RETRY_BASE_SLEEP_SECONDS: float = 0.5

    def __init__(self, name: str, aws_service: str = "s3"):
        """
        Constructor

        :param name: Name for logging as to whose behalf this class is operating.
        :param aws_service: Name of the AWS service to initialize the boto client
        """
        self.name: str = name
        self.aws_service: str = aws_service
        self.logger: Logger = getLogger(self.__class__.__name__)

        # Sync lock is only needed to properly create the async lock
        # at the right time in the right thread.
        self.sync_lock: SyncLock = SyncLock()
        self.async_aws_client_lock: AsyncLock = None

        # Boto Machinations
        # We should be able to have a single Session for the lifetime of this
        # object. It is only discarded - to force the credential chain to be
        # re-resolved - if S3 rejects the credentials a request was signed
        # with (see retry_with_new_client).
        self.session: AioSession = None

    async def retry_with_new_client(self, work_function: Callable, *, source: str = None) -> Any:
        """
        Retries the async work_function when client credentials can expire.

        Because clients are created keyless (see class docstring),
        token-based credentials refresh at signing time and this retry path
        stays dormant for them. It exists for static SESSION TOKENS rotated
        externally - temporary credentials in a credentials file that
        another process rewrites. The credential chain is resolved once per
        Session and that file is never re-read on its own, so the only way
        to pick up the new values is to discard the session and re-resolve
        from scratch. Two rotation cases deliberately do NOT recover here:
        environment variables (a process's environment cannot be changed
        from outside, so re-resolving would re-read the same values), and
        rotated access KEY PAIRS (S3 rejects those with InvalidAccessKeyId
        or SignatureDoesNotMatch, not ExpiredToken). Both require a
        process restart.

        NOTE: mirrored in AwsSyncClientWorker.retry_with_new_client() -
        keep the retry policies in sync when editing.

        :param work_function: The async work function to retry
        :param source: A string describing where the deployment was coming from
        :return: What work_function returns
        """

        # Async lock has to be created in the thread that uses it.
        self.ensure_async_lock_exists()

        last_err: Exception = None

        for attempt in range(1, self.CREDENTIAL_RETRY_MAX_ATTEMPTS + 1):
            # Obtain the session up front so the except block below can tell
            # whether the session it wants to discard is still the one this
            # attempt actually failed with.
            session: AioSession = await self.get_or_create_session()
            try:
                retval: Any = await self.do_work_with_new_client(session, work_function, attempt=attempt)
                return retval

            except ClientError as err:
                # S3Util.is_expired_token_error() is used instead of raw
                # DictionaryExtractor access: the extractor returns a stored
                # None in preference to its default, and
                # '"ExpiredToken" not in None' would raise TypeError inside
                # this handler, masking the original ClientError
                # (see S3Util.get_error_code for details).
                if not S3Util.is_expired_token_error(err):
                    raise

                last_err = err

                # Discard the session so the next attempt re-resolves the
                # credential chain from scratch - but only if it is still
                # the session this attempt failed with. A concurrent batch's
                # retry may already have rebuilt a fresh session; discarding
                # that would just force a redundant chain re-resolution.
                if self.session is session:
                    self.session = None
                if source is None:
                    source = self.name
                self.logger.warning("%s (%d): %s credentials seem to have expired. Retrying. "
                                    "If you believe you have non-expiring %s credentials, be sure they are correct.",
                                    source, attempt, self.aws_service, self.aws_service)
                if attempt < self.CREDENTIAL_RETRY_MAX_ATTEMPTS:
                    # Jittered backoff gives an in-progress external rotation
                    # time to land and keeps concurrent retries from hammering
                    # the credential chain's network sources back-to-back.
                    await async_sleep(S3Util.exponential_backoff_with_jitter(
                        self.CREDENTIAL_RETRY_BASE_SLEEP_SECONDS, attempt))

        # Exhausted retries. Every path that exits the loop sets last_err
        # first, so this raise always fires; the RuntimeError below is an
        # unreachable backstop that keeps the exhaustion path explicit.
        if last_err is not None:
            raise last_err

        raise RuntimeError(f"{self.aws_service} credential retries exhausted without capturing an error")

    async def get_or_create_session(self) -> AioSession:
        """
        :return: The worker's shared AioSession, creating it on first use
                 (or after the credential retry discarded it).
        Creation is serialized under the same async lock that serializes
        client creation, so concurrent batches share one session instead of
        racing to build several.
        """
        async with self.async_aws_client_lock:
            if self.session is None:
                self.session = get_session()
            return self.session

    def ensure_async_lock_exists(self):
        """
        Be sure we have an asynchronous Lock to get our sessions.
        """
        # Note that none of this is async in and of itself.
        if self.async_aws_client_lock is None:
            with self.sync_lock:
                # Be sure everyone has the same lock
                if self.async_aws_client_lock is None:
                    self.async_aws_client_lock = AsyncLock()

    async def do_work_with_new_client(self, session: AioSession, work_function: Callable, *,
                                      attempt: int = 1) -> Any:
        """
        This method separates the machinations of obtaining a proper S3 client
        from add_all_reservations() which does all the actual work.

        :param session: The AioSession to create the client from. Passed in
                (rather than read from self.session here) so the caller's
                credential-retry handler knows exactly which session this
                attempt used and can avoid discarding a fresh one built by
                a concurrent batch.
        :param work_function: The async work function to retry
        :param attempt: Attempt number
        :return: What work_function returns
        """

        retval: Any = None

        # Create an aiobotocore client for async operations.
        async_aws_client: AioBaseClient = None

        async_aws_client_creator_context: ClientCreatorContext = None
        lock_released: bool = False
        acquired_lock: bool = False

        start_time: float = perf_counter()
        lock_aquired_time: float = 0.0
        client_created_time: float = 0.0
        lock_released_time: float = 0.0
        try:
            # Serialize creation of the ClientCreatorContext with the lock to avoid credential-chain races.
            await self.async_aws_client_lock.acquire()
            lock_aquired_time = perf_counter()
            acquired_lock = True

            # No aws_access_key_id/aws_secret_access_key/aws_session_token
            # arguments here: passing them would pin a static snapshot of the
            # credentials into the client and disable at-signing-time refresh
            # (see class docstring).
            async_aws_client_creator_context = session.create_client(self.aws_service)
            client_created_time = perf_counter()

            # Normally this is done in a python ContextManager using a with-statement,
            # but we want to be holding the lock while we create the client to avoid
            # credential-chain races like NoCredentialsError.

            async with async_aws_client_creator_context as async_aws_client:

                # Release the lock while we process, allowing other tasks to work on
                # getting their own async_aws_client. (Not an async method)
                self.async_aws_client_lock.release()
                lock_released_time = perf_counter()
                lock_released = True

                retval = await work_function(async_aws_client=async_aws_client)

        finally:
            # Always release the lock if we successfully acquired it and have not already done so,
            # in case there was an error getting/entering the context manager.
            if acquired_lock and not lock_released:
                self.async_aws_client_lock.release()

        finish_time: float = perf_counter()
        self.logger.info("%s (%d): Lock acquisition in: %fs. Client context creation after: %fs. "
                         "Lock release after: %fs. Finish after: %fs",
                         self.name, attempt,
                         lock_aquired_time - start_time,
                         client_created_time - start_time,
                         lock_released_time - start_time,
                         finish_time - start_time)
        return retval

    @staticmethod
    async def do_with_retries(source: str, fn, *, max_attempts: int = 8, base_sleep: float = 0.25):
        """
        Generic retry wrapper for boto3 calls.
        boto3/botocore already retries, but this adds a bit of extra resilience and backoff for batch operations.
        """
        sleep: float = 0.0
        attempt: int = 1
        while True:
            try:
                return await fn()
            except ClientError as err:
                if attempt >= max_attempts or not S3Util.is_retryable_client_error(err):
                    raise

                sleep = S3Util.exponential_backoff_with_jitter(base_sleep, attempt)
                _SENSITIVE_LOGGER.warning("%s: Retryable async ClientError (%s). attempt=%d", source, err, attempt)
                await async_sleep(sleep)
                attempt += 1
            except NoCredentialsError:
                # Must precede the BotoCoreError catch below (it is a
                # subclass): missing credentials cannot heal within this
                # loop - the calling client's credential state is fixed -
                # so backing off through 8 attempts (~16-48s of sleeps)
                # would only stall the write queue before failing anyway.
                raise
            except BotoCoreError as err:
                # Often transient network/serialization issues
                if attempt >= max_attempts:
                    raise

                sleep = S3Util.exponential_backoff_with_jitter(base_sleep, attempt)
                _SENSITIVE_LOGGER.warning("%s: Retryable async BotoCoreError (%s). attempt=%d", source, err, attempt)
                await async_sleep(sleep)
                attempt += 1
            except CancelledError:
                _LOGGER.info("%s: async Task was cancelled.", source)
                raise
            except Exception as err:  # pylint: disable=broad-except
                # Catch-all for unexpected exceptions; log and re-raise
                _SENSITIVE_LOGGER.error("%s: Unexpected async error (%s). attempt=%d", source, err, attempt)
                raise
