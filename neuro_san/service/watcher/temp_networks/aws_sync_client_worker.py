
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
from typing import Optional

from time import sleep as sync_sleep

from logging import getLogger
from logging import Logger
from threading import Lock as SyncLock

from botocore.client import BaseClient
from botocore.config import Config
from botocore.exceptions import BotoCoreError
from botocore.exceptions import ClientError
from botocore.exceptions import NoCredentialsError
from botocore.session import get_session
from botocore.session import Session

from leaf_common.logging.sensitive_logger import SensitiveLogger

from neuro_san.service.watcher.temp_networks.s3_util import S3Util

# Module-level so the hot-path do_with_retries() below does not construct
# them per call: logging.getLogger() takes the process-global logging lock
# on every invocation, and do_with_retries() runs once per reservation read.
_LOGGER: Logger = getLogger(__name__)
_SENSITIVE_LOGGER: SensitiveLogger = SensitiveLogger(_LOGGER)


class AwsSyncClientWorker:
    """
    Class that manages a particular AWS boto synchronous work_function
    (from functools.partial) that has sync_aws_client as an argument,
    supplying it with a single long-lived botocore client.

    Credential handling is delegated to botocore by creating the client
    WITHOUT explicit keys: such a client holds the session's credential
    OBJECT and freezes it per request at signing time. For token-based
    credential sources (IAM Instance Role, ECS Task Role, AWS SSO/IAM
    Identity Center) that object is RefreshableCredentials, which checks
    its expiry window on every request and refreshes itself BEFORE
    signing - so a long-lived keyless client never presents an expired
    token to S3, and token rotation costs zero failed calls.
    See: https://docs.aws.amazon.com/boto3/latest/guide/credentials.html

    The previous design instead froze the session's credentials once and
    passed the raw key/secret/token to create_client() - which makes
    botocore build a static Credentials object with NO refresh machinery -
    and created/closed a client around every work_function call,
    discarding the client's urllib3 connection pool each time. That put
    client construction (serialized under a worker-wide lock) plus a
    fresh TCP+TLS handshake on every S3 call, on a read path that runs
    per request for reservation-cache misses, and made token-expiry
    recovery reactive: one real failed ExpiredToken round trip per expiry
    cycle. See issue #1153.
    """

    # The one long-lived client serves ALL concurrent readers through its
    # connection pool. botocore's default pool holds only 10 connections
    # (with urllib3 block=False), so any concurrency beyond that silently
    # opens a fresh TCP+TLS connection per request and discards it on
    # release ("Connection pool is full" warnings) - exactly the handshake
    # cost this long-lived client exists to avoid. Size the pool for the
    # server's request-thread concurrency instead.
    MAX_POOL_CONNECTIONS: int = 50

    # Credential-retry policy for retry_with_new_client(): enough attempts,
    # with short jittered backoff between them, to ride out a several-second
    # external rotation window (a credentials file being rewritten) without
    # hanging the request path for tens of seconds. Backoff matters here
    # because each attempt re-resolves the full credential chain (possibly
    # network calls to IMDS/ECS/SSO) - back-to-back attempts would hammer
    # those endpoints and still fail before the rotation lands.
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

        # Guards creation/reset of the session + client pair below.
        # Only (re)creation is serialized; once created, the client is used
        # WITHOUT the lock - botocore clients are thread-safe and serve
        # concurrent requests through their connection pool, so no
        # per-request serialization point is needed.
        self.sync_aws_client_lock: SyncLock = SyncLock()

        # One Session and one client for the lifetime of this object.
        # They are only discarded - together, by reset_client() - if S3
        # rejects the credentials a request was signed with
        # (see retry_with_new_client).
        self.session: Session = None
        self.sync_aws_client: BaseClient = None

    def retry_with_new_client(self, work_function: Callable, *, source: str = None) -> Any:
        """
        Calls work_function with this worker's long-lived S3 client,
        retrying with a rebuilt session + client should S3 reject the
        credentials a request was signed with.

        Because the client is keyless (see class docstring), token-based
        credentials refresh at signing time and this retry path stays
        dormant for them. It exists for static SESSION TOKENS rotated
        externally - temporary credentials in a credentials file that
        another process rewrites. botocore resolves the credential chain
        once per Session and never re-reads that file on its own, so the
        only way to pick up the new values is to discard the session and
        client and re-resolve from scratch (reset_client()). Two rotation
        cases deliberately do NOT recover here: environment variables
        (a process's environment cannot be changed from outside, so
        re-resolving would re-read the same values), and rotated access
        KEY PAIRS (S3 rejects those with InvalidAccessKeyId or
        SignatureDoesNotMatch, not ExpiredToken - widening the gate to
        match them would make genuine signing bugs retry instead of
        surfacing). Both of those require a process restart.

        NOTE: mirrored in AwsAsyncClientWorker.retry_with_new_client() -
        keep the retry policies in sync when editing.

        :param work_function: The work function to retry
        :param source: A string describing where the deployment was coming from
        :return: What work_function returns
        """

        last_err: Exception = None

        for attempt in range(1, self.CREDENTIAL_RETRY_MAX_ATTEMPTS + 1):
            try:
                sync_aws_client: BaseClient = self.get_client()
                retval: Any = work_function(sync_aws_client=sync_aws_client)
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

                # Discard the session + client so the next attempt re-resolves
                # the credential chain from scratch. Passing the client this
                # attempt actually failed with lets reset_client() skip the
                # reset when a concurrent thread already rebuilt a fresh one.
                self.reset_client(failed_client=sync_aws_client)
                if source is None:
                    source = self.name
                self.logger.warning("%s (%d): %s credentials seem to have expired. Retrying. "
                                    "If you believe you have non-expiring %s credentials, be sure they are correct.",
                                    source, attempt, self.aws_service, self.aws_service)
                if attempt < self.CREDENTIAL_RETRY_MAX_ATTEMPTS:
                    # Jittered backoff gives an in-progress external rotation
                    # time to land and keeps concurrent retries from hammering
                    # the credential chain's network sources back-to-back.
                    sync_sleep(S3Util.exponential_backoff_with_jitter(
                        self.CREDENTIAL_RETRY_BASE_SLEEP_SECONDS, attempt))

        # Exhausted retries. Every path that exits the loop sets last_err
        # first, so this raise always fires; the RuntimeError below is an
        # unreachable backstop that keeps the exhaustion path explicit.
        if last_err is not None:
            raise last_err

        raise RuntimeError(f"{self.aws_service} credential retries exhausted without capturing an error")

    def get_client(self) -> BaseClient:
        """
        :return: This worker's long-lived S3 client, created (along with
                 its Session) on first use.

        The client is created WITHOUT explicit keys, which is what keeps
        botocore's at-signing-time credential refresh in play (see class
        docstring). Creation is serialized under the lock so concurrent
        first callers cannot race the credential chain; after that,
        callers get the cached client for the cost of one unlocked
        attribute read.
        """
        # Unlocked fast path: after first creation, this read is the whole
        # cost of client acquisition on the read hot path.
        local_client: BaseClient = self.sync_aws_client
        if local_client is not None:
            return local_client

        with self.sync_aws_client_lock:
            # Double-checked: another thread may have created the client
            # while we waited on the lock.
            if self.sync_aws_client is None:
                # We should only need one Session for the lifetime of this
                # object (until reset_client() forces re-resolution).
                if self.session is None:
                    self.session = get_session()

                # Guard against poisoning the cache: create_client() pins
                # whatever the chain resolves RIGHT NOW into the client -
                # including None (an empty chain, e.g. a credentials file
                # mid-rewrite during rotation). A client pinned with None
                # raises NoCredentialsError - a BotoCoreError the
                # ExpiredToken retry above can never see - on every request,
                # so caching it would wedge this worker until restart.
                # Raising here instead leaves the cache empty, and
                # Session.get_credentials() re-resolves whenever its previous
                # resolution came back None, so the worker self-heals on the
                # next call once credentials are available again.
                if self.session.get_credentials() is None:
                    raise NoCredentialsError()

                # No aws_access_key_id/aws_secret_access_key/aws_session_token
                # arguments here: passing them would pin a static snapshot of
                # the credentials into the client and disable auto-refresh.
                self.sync_aws_client = self.session.create_client(
                    self.aws_service,
                    config=Config(max_pool_connections=self.MAX_POOL_CONNECTIONS))
                self.logger.info("%s: Created long-lived %s client", self.name, self.aws_service)

            return self.sync_aws_client

    def reset_client(self, failed_client: Optional[BaseClient] = None):
        """
        Discard the long-lived client AND its Session so the next
        get_client() re-resolves the credential chain from scratch.
        Discarding only the client would not be enough: the stale resolved
        credentials live on the Session, and a new client built from the
        old Session would just reuse them.

        The old client is deliberately dropped without close(): other
        threads may still be mid-request on it, and close() would tear the
        connection pool out from under them. Dropping the reference lets
        in-flight calls finish; the pool is released with the client
        object once the last reference is gone.

        :param failed_client: When given, only reset if this is still the
                cached client. During a rotation, N threads that all failed
                on the OLD client would otherwise serially discard the fresh
                session+client the first thread's retry already rebuilt,
                forcing N redundant credential-chain re-resolutions.
                Omit (None) for an unconditional administrative reset.
        """
        with self.sync_aws_client_lock:
            if failed_client is not None and self.sync_aws_client is not failed_client:
                return
            self.sync_aws_client = None
            self.session = None

    @staticmethod
    def do_with_retries(source: str, fn, *, max_attempts: int = 8, base_sleep: float = 0.25):
        """
        Generic retry wrapper for boto3 calls.
        boto3/botocore already retries, but this adds a bit of extra resilience and backoff for batch operations.
        """
        sleep: float = 0.0
        attempt: int = 1
        while True:
            try:
                return fn()
            except ClientError as err:
                if attempt >= max_attempts or not S3Util.is_retryable_client_error(err):
                    raise

                sleep = S3Util.exponential_backoff_with_jitter(base_sleep, attempt)
                _SENSITIVE_LOGGER.warning("%s: Retryable sync ClientError (%s). attempt=%d", source, err, attempt)
                sync_sleep(sleep)
                attempt += 1
            except NoCredentialsError:
                # Must precede the BotoCoreError catch below (it is a
                # subclass): missing credentials cannot heal within this
                # loop - the calling client's credential state is fixed -
                # so backing off through 8 attempts (~16-48s of sleeps)
                # would only stall the request path before failing anyway.
                raise
            except BotoCoreError as err:
                # Often transient network/serialization issues
                if attempt >= max_attempts:
                    raise

                sleep = S3Util.exponential_backoff_with_jitter(base_sleep, attempt)
                _SENSITIVE_LOGGER.warning("%s: Retryable sync BotoCoreError (%s). attempt=%d", source, err, attempt)
                sync_sleep(sleep)
                attempt += 1
            except Exception as err:  # pylint: disable=broad-except
                # Catch-all for unexpected exceptions; log and re-raise
                _SENSITIVE_LOGGER.error("%s: Unexpected sync error (%s). attempt=%d", source, err, attempt)
                raise
