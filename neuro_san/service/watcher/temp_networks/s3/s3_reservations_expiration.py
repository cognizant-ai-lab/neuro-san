
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
from typing import Dict
from typing import Iterable
from typing import Optional
from typing import Type

from time import time
from functools import partial

from json.decoder import JSONDecodeError
from logging import getLogger
from logging import Logger

from leaf_common.config.resolver_util import ResolverUtil

# Lazily resolve here because this is one of the first places the import happens
BaseClient: Type[Any] = ResolverUtil.create_type("botocore.client.BaseClient", install_if_missing="botocore")
ClientError: Type[Any] = ResolverUtil.create_type("botocore.exceptions.ClientError", install_if_missing="botocore")

from neuro_san.interfaces.reservationist import Reservationist                                              # noqa: E402
from neuro_san.service.watcher.temp_networks.s3.aws_sync_client_worker import AwsSyncClientWorker           # noqa: E402
from neuro_san.service.watcher.temp_networks.s3.s3_reservations_retriever import S3ReservationsRetriever    # noqa: E402
from neuro_san.service.watcher.temp_networks.s3.s3_util import S3Util                                       # noqa: E402


class S3ReservationsExpiration:
    """
    Handles expiration of Reservations from S3 storage.

    The main entry point to this guy is expire_reservations() which gets called as part of
    S3ReservationsStorage watcher loop.
    """

    # Grace period before an object under the prefix that does not parse as a
    # reservation is deleted (see handle_malformed_object). Every reservation
    # has a bounded lifetime (clamped against a server max, which defaults to
    # Reservationist.DEFAULT_LIFETIME), so an object that has existed for
    # twice that cannot be a live reservation under ANY schema version.
    # Deployments that raise the server max lifetime beyond the default
    # should raise this accordingly.
    MALFORMED_OBJECT_GRACE_SECONDS: float = 2 * Reservationist.DEFAULT_LIFETIME

    def __init__(self, name: str = "S3ReservationsExpiration", bucket_name: str = "",
                 prefix: str = S3Util.DEFAULT_RESERVATIONS_PREFIX):
        """
        Initialize S3 reservations storage.

        :param name: Name of this writer
        :param bucket_name: S3 bucket name (defaults to AGENT_RESERVATIONS_S3_BUCKET env var)
        :param prefix: S3 key prefix for reservation objects
        """
        # Our default for check_expirations_interval_seconds is 0
        # because S3 expiration check is generally a significant execution load,
        # and we may want to run it externally on demand rather than on a fixed schedule inside the service.
        self.name: str = name
        self.logger: Logger = getLogger(self.__class__.__name__)

        self.retriever = S3ReservationsRetriever(name=self.name, bucket_name=bucket_name, prefix=prefix)
        self.max_keys_per_page: int = 1000  # Max allowed by S3 API for ListObjectsV2

    def start(self):
        """
        Validate connection to the bucket, creating the worker's long-lived
        S3 client on first use.

        Calling this again only re-validates bucket access through that same
        client; it does not rebuild the client or re-resolve credentials
        (that happens in AwsSyncClientWorker.reset_client(), driven by its
        credential retry).
        """
        self.retriever.start()

    def expire_reservations(self):
        """
        Remove expired reservations from S3 storage.
        """
        self.logger.debug("%s: Starting expiration process for S3 reservations", self.name)

        expire_function: Callable = partial(self.expire_any_reservations)

        client_worker: AwsSyncClientWorker = self.retriever.get_sync_client_worker()
        client_worker.retry_with_new_client(expire_function, source=self.name)

    def expire_any_reservations(self, sync_aws_client: BaseClient = None):
        """
        Remove expired reservations from S3 storage.
        :param sync_aws_client: S3 client
        """
        # Track how many reservations we expire for reporting
        expired_count: int = 0
        # Get current timestamp once for consistent expiration checking
        current_time: float = time()

        for reservation_key in self.iter_reservation_keys(sync_aws_client):
            if not reservation_key:
                continue
            # Attempt to expire this reservation and increment counter if successful
            if self.expire_one_reservation(reservation_key, current_time, sync_aws_client=sync_aws_client):
                expired_count += 1

        if expired_count > 0:
            self.logger.info("%s: Expiration complete: removed %d expired reservations from S3",
                             self.name, expired_count)
        else:
            self.logger.debug("%s: Expiration complete: removed no expired reservations from S3", self.name)

    def iter_reservation_keys(self, sync_aws_client: BaseClient) -> Iterable[str]:
        """
        Lists ALL objects under the current S3 bucket prefix and yields their
        object keys.

        Pages through results by calling list_objects_v2 directly with
        ContinuationToken rather than using a boto3 Paginator. Each
        list_objects_v2 call is a single, eager HTTP request, so wrapping it
        in do_with_retries() gives correct per-page retry semantics for
        transient ClientError/BotoCoreError: each page fetch is retried in
        isolation, and the ContinuationToken from the previous successful
        response is only consulted after that response has actually arrived.
        """
        client_worker: AwsSyncClientWorker = self.retriever.get_sync_client_worker()

        continuation_token = None
        while True:
            kwargs = {
                "Bucket": self.retriever.get_bucket_name(),
                "Prefix": self.retriever.get_prefix(),
                "MaxKeys": self.max_keys_per_page,
            }
            if continuation_token:
                kwargs["ContinuationToken"] = continuation_token

            list_objects_function: Callable = partial(sync_aws_client.list_objects_v2, **kwargs)
            response = client_worker.do_with_retries(self.name, list_objects_function)
            if response is None:
                response = {}
            for obj in response.get("Contents", []):
                yield obj.get("Key")
            if not response.get("IsTruncated"):
                # This was the last page - exit loop
                break
            continuation_token = response.get("NextContinuationToken")
            if not continuation_token:
                # S3's ListObjectsV2 contract pairs IsTruncated=True with a
                # NextContinuationToken, so real S3 never lands here. But if a
                # non-compliant S3-compatible endpoint (or a test fake) omits
                # the token, looping again without it would re-request the
                # first page forever - an infinite loop that also burns S3 API
                # calls for every re-listed key. Keep the failure loud
                # rather than looping silently.
                raise RuntimeError(
                    f"{self.name}: list_objects_v2 returned IsTruncated=True without a "
                    "NextContinuationToken; aborting listing to avoid an infinite pagination loop")

    # pylint: disable=too-many-locals
    def expire_one_reservation(self, obj_key: str, current_time: float,
                               source: str = None, sync_aws_client: BaseClient = None) -> bool:
        """
        Check and expire a single reservation if it's expired.

        :param obj_key: S3 object key for the reservation
        :param current_time: Current timestamp to compare against
        :return: True if reservation was expired and deleted, False otherwise
        """
        if source is None:
            source = self.name

        expired: bool = False
        try:
            # Retrieve the reservation object from S3. The parsed body can be
            # any JSON type (not just a dict) - extract_reservation_data()
            # below is designed to accept and validate exactly that.
            agent_spec: Any = self.retriever.retrieve_object_with_retries(
                obj_key=obj_key,
                source=source,
                sync_aws_client=sync_aws_client
            )

            reservation_data: Optional[Dict[str, Any]] = S3Util.extract_reservation_data(agent_spec)
            if reservation_data is None:
                # Not shaped like a reservation. Note that a stored
                # expiration_time_in_seconds of None/null lands HERE too:
                # extract_reservation_data() returns None for the whole
                # payload when that field is missing, null, or non-numeric.
                return self.handle_malformed_object(obj_key, current_time,
                                                    sync_aws_client=sync_aws_client)

            client_worker: AwsSyncClientWorker = self.retriever.get_sync_client_worker()

            # Compare current time against reservation's expiration timestamp.
            # What if expiration_time_in_seconds is None (a stored JSON null)
            # or missing? It cannot be, by this line: null, missing, bool and
            # non-numeric values all fail extract_reservation_data()'s
            # isinstance check, which returns None for the WHOLE payload, and
            # that case exits above via handle_malformed_object(). Here the
            # value is guaranteed to be an int or float, so no default is
            # needed and this comparison cannot raise TypeError.
            expiration_time: float = reservation_data.get("expiration_time_in_seconds")
            if current_time > expiration_time:
                # Reservation has expired - remove it from S3 storage
                try:
                    delete_function: Callable = partial(sync_aws_client.delete_object,
                                                        Bucket=self.retriever.get_bucket_name(),
                                                        Key=obj_key)
                    client_worker.do_with_retries(source, delete_function)
                    reservation_id: str = reservation_data.get("id", "<unknown>")
                    self.logger.debug("%s: Deleted expired reservation %s from S3", self.name, reservation_id)
                    expired = True
                except ClientError as delete_error:
                    # Handle case where another process already deleted the object.
                    # get_error_code() is used instead of raw response access because
                    # it always returns a str, even when the parsed error body stores
                    # Code as null (see S3Util.get_error_code for details).
                    if S3Util.get_error_code(delete_error) != "NoSuchKey":
                        # Re-raise other delete errors
                        raise delete_error

                    self.logger.debug("%s: Reservation %s was already deleted by another process", self.name, obj_key)
                    expired = True  # Consider this a successful expiration

            # Reservation is still active - no action needed

        except ClientError as exception:
            error_code: str = S3Util.get_error_code(exception)
            # Handle case where another process already removed the object
            # before we could read it. Two codes mean "gone": GET errors carry
            # NoSuchKey in the response body, while HEAD errors (from the
            # malformed-path head_object age check) have no body for botocore
            # to parse, so a missing key surfaces as the bare HTTP status "404".
            if error_code in ("NoSuchKey", "404"):
                self.logger.debug("%s: Reservation %s was already removed by another process", self.name, obj_key)
                expired = True  # Object is gone, which is the desired outcome for expiration
            elif S3Util.is_credential_rejection_error(exception):
                # Credential rejection (ExpiredToken / InvalidToken) must NOT be
                # swallowed here. The sweep's client is keyless and long-lived (see
                # AwsSyncClientWorker), so token-based credentials refresh at signing
                # time and this path stays dormant for them - but it can still fire
                # for static session tokens rotated externally (a credentials file
                # rewritten by another process), which botocore resolves once per
                # Session and never re-reads, or for a malformed/mismatched
                # credential state (InvalidToken - see
                # S3Util.is_credential_rejection_error). The only code that can
                # recover is retry_with_new_client() wrapping
                # expire_any_reservations() at the top of the sweep - and it can only
                # react to ClientErrors that actually reach it. If these errors were
                # merely logged like the codes below, every remaining key in the
                # sweep would make one doomed S3 call, nothing would be expired, and
                # the sweep would still report success. Re-raising lets the wrapper
                # rebuild the session + client and re-run the sweep with working
                # credentials. Restarting the sweep is safe because deletes are
                # idempotent: NoSuchKey on the re-run is treated as success above.
                #
                # Caveat: this match only works for errors with a parseable body
                # (GET/DELETE). An expired-token rejection of head_object surfaces
                # as the bare status "400" (HEAD errors have no body - same reason
                # as the "404" case above), misses this branch, and is logged by
                # the else below; the sweep then recovers on the next key's GET,
                # whose ExpiredToken body does reach this re-raise.
                raise
            else:
                # Log other S3 errors but don't raise - allows expiration to continue
                self.logger.error("%s: S3 error processing reservation object %s: %s",
                                  self.name, obj_key, str(exception))

        except JSONDecodeError as exception:
            # Log JSON errors but don't raise - allows expiration process to continue
            self.logger.error("%s: JSON error processing reservation object %s during expire: %s",
                              self.name, obj_key, str(exception))

        return expired

    def handle_malformed_object(self, obj_key: str, current_time: float,
                                sync_aws_client: BaseClient = None) -> bool:
        """
        Policy for objects under the reservations prefix that do not parse as
        reservations (see S3Util.extract_reservation_data). Four behaviors are
        possible here, and each has been tried or considered:
          1. Raise: one malformed object makes every sweep crash at the same
             key ("'NoneType' object has no attribute 'get'"), so nothing
             sorted after it ever expires.
          2. Treat as expired and delete immediately: silently destroys any
             object whose shape we merely fail to understand - including a
             live reservation written by a newer schema version during a
             rolling deploy.
          3. Skip and warn forever: safe for the data, but unparseable
             detritus builds up and gets re-read and re-logged on every pass.
          4. Age-gated delete (current): skip and WARN while the object is
             younger than MALFORMED_OBJECT_GRACE_SECONDS, then delete it with
             a WARNING. Every reservation has a bounded lifetime, so once an
             object has existed longer than any reservation could live, no
             schema version can still consider it live - deleting it is safe,
             detritus is bounded, and the warnings during the grace period
             give humans a window to notice and diagnose schema drift.

        :param obj_key: S3 object key of the unparseable object
        :param current_time: Current timestamp to compare against
        :param sync_aws_client: S3 client
        :return: True if the object was deleted (counted as expired),
                 False if it was left in place for now
        """
        client_worker: AwsSyncClientWorker = self.retriever.get_sync_client_worker()

        # The object's age comes from S3's LastModified via head_object. This
        # extra call happens only on this (rare) malformed path, never during
        # a normal sweep. Any ClientError it raises is handled by
        # expire_one_reservation()'s handler, with a HEAD-specific wrinkle:
        # HEAD error responses have no body for botocore to parse, so they
        # surface as bare HTTP status codes - a missing key is "404" (treated
        # there as already-removed) and an expired token is "400" (logged and
        # skipped there; the sweep recovers on the next key's GET, which
        # carries a parseable ExpiredToken code).
        head_function: Callable = partial(sync_aws_client.head_object,
                                          Bucket=self.retriever.get_bucket_name(),
                                          Key=obj_key)
        head_response: Dict[str, Any] = client_worker.do_with_retries(self.name, head_function)

        last_modified: Any = head_response.get("LastModified")
        if last_modified is None:
            # No age available: err on the side of keeping data this pass.
            age_in_seconds: float = 0.0
        else:
            age_in_seconds = current_time - last_modified.timestamp()

        if age_in_seconds <= self.MALFORMED_OBJECT_GRACE_SECONDS:
            self.logger.warning(
                "%s: Object %s under the reservations prefix does not parse as a "
                "reservation (missing/null metadata.reservation or non-numeric "
                "expiration_time_in_seconds). Leaving it in place for now; if it is "
                "still unparseable %d seconds after its last modification, it will be "
                "deleted. If this recurs for objects the writer produced, check for "
                "schema drift.",
                self.name, obj_key, int(self.MALFORMED_OBJECT_GRACE_SECONDS))
            return False

        delete_function: Callable = partial(sync_aws_client.delete_object,
                                            Bucket=self.retriever.get_bucket_name(),
                                            Key=obj_key)
        client_worker.do_with_retries(self.name, delete_function)
        self.logger.warning(
            "%s: Deleted unparseable object %s: last modified %s, older than the "
            "%d-second grace period. No reservation lives that long, so no schema "
            "version could still consider it live.",
            self.name, obj_key, last_modified, int(self.MALFORMED_OBJECT_GRACE_SECONDS))
        return True
