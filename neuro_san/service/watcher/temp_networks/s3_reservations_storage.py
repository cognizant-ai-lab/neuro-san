
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
from typing import Dict
from typing import Iterable
from typing import Tuple

import os
import random
import time
from functools import partial

from json import dumps
from json import loads
from json.decoder import JSONDecodeError
from logging import getLogger
from logging import Logger

from boto3 import client as boto3_client
from botocore.client import BaseClient
from botocore.exceptions import BotoCoreError
from botocore.exceptions import ClientError
from botocore.exceptions import NoCredentialsError

from neuro_san.interfaces.reservation import Reservation
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.network_providers.abstract_reservations_storage \
    import AbstractReservationsStorage
from neuro_san.internals.reservations.reservation_dictionary_converter import ReservationDictionaryConverter


class S3ReservationsStorage(AbstractReservationsStorage):
    """
    AWS S3-based implementation of ReservationsStorage.

    Stores reservations as JSON objects in an S3 bucket, with each reservation
    stored in its associated agent spec as metadata.
    """
    # pylint: disable=too-many-instance-attributes

    def __init__(self, bucket_name: str = "", prefix: str = "reservations/",
                 check_expirations_interval_seconds: float = 0.0):
        """
        Initialize S3 reservations storage.

        :param bucket_name: S3 bucket name (defaults to AGENT_RESERVATIONS_S3_BUCKET env var)
        :param prefix: S3 key prefix for reservation objects
        :param check_expirations_interval_seconds: How often to check for expired reservations.
                                    If 0 or negative, expiration checks are disabled.
        """
        # Our default for check_expirations_interval_seconds is 0
        # because S3 expiration check is generally a significant execution load,
        # and we may want to run it externally on demand rather than on a fixed schedule inside the service.
        super().__init__(storage_name="s3_storage",
                         check_expirations_interval_seconds=check_expirations_interval_seconds)
        self.logger: Logger = getLogger(self.__class__.__name__)

        # Check if expiration interval is set by environment variable,
        # and adjust it if so (overriding the constructor parameter)
        envvar_name: str = "AGENT_RESERVATIONS_EXTERNAL_STORAGE_CHECK_PERIOD_SECONDS"
        envvar_value: str = os.getenv(envvar_name, "0")
        try:
            expiration_check_period_seconds: float = float(envvar_value)
            self._check_interval_seconds = expiration_check_period_seconds
        except ValueError as exc:
            self.logger.error(
                "Invalid value for %s, must be a number. Got: %s. "
                "Please correct the environment variable or unset it.",
                envvar_name,
                envvar_value,
            )
            raise ValueError(
                f"Invalid value for {envvar_name}: expected a numeric value, got {envvar_value!r}"
            ) from exc

        # Configure bucket name from parameter or environment variable
        env_bucket: str = os.getenv("AGENT_RESERVATIONS_S3_BUCKET", "")
        self.bucket_name: str = bucket_name or env_bucket
        if not self.bucket_name:
            raise ValueError(
                "S3 bucket name must be provided via bucket_name parameter or "
                "AGENT_RESERVATIONS_S3_BUCKET environment variable"
            )

        # Set up S3 key prefix and initialize sync target
        self.prefix: str = prefix
        self.s3_client: BaseClient = None

        # Track last sync timestamp for incremental syncing (0.0 means sync all)
        self.last_sync_timestamp: float = 0.0
        self.converter = ReservationDictionaryConverter()
        self.max_keys_per_page: int = 1000  # Max allowed by S3 API for ListObjectsV2

    def start(self):
        """
        Initialize the S3 client and validate connection to the bucket.

        This method can be called to re-initialize the connection if needed.
        """
        try:
            # Initialize S3 client using default AWS credential chain
            self.s3_client = boto3_client("s3")

            # Validate bucket exists and we have access by performing a head operation
            self.s3_client.head_bucket(Bucket=self.bucket_name)
            self.logger.info("%s: Successfully connected to S3 bucket: %s", self._name, self.bucket_name)

        except NoCredentialsError as exception:
            # Handle missing AWS credentials
            raise ValueError(f"{self._name}: AWS credentials not found. Please configure AWS credentials.") \
                from exception
        except ClientError as exception:
            # Handle various S3 access errors with specific messages
            error_code: str = exception.response["Error"]["Code"]
            if error_code == "404":
                raise ValueError(f"{self._name}: S3 bucket '{self.bucket_name}' does not exist") from exception
            if error_code == "403":
                raise ValueError(f"{self._name}: Access denied to S3 bucket '{self.bucket_name}'") from exception
            raise ValueError(f"{self._name}: Error accessing S3 bucket '{self.bucket_name}': {exception}") \
                from exception
        # We are good with S3 connection and bucket access at this point,
        # let's start underlying logic:
        super().start()

    def _is_retryable_client_error(self, err: ClientError) -> bool:
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

    def _do_with_retries(self, fn, *, max_attempts: int = 8, base_sleep: float = 0.25):
        """
        Generic retry wrapper for boto3 calls.
        boto3/botocore already retries, but this adds a bit of extra resilience and backoff for batch operations.

        """
        attempt: int = 1
        while True:
            try:
                return fn()
            except ClientError as err:
                if attempt >= max_attempts or not self._is_retryable_client_error(err):
                    raise
                # Compute exponential backoff with jitter
                sleep = base_sleep * (2 ** (attempt - 1))
                sleep = sleep * (0.5 + random.random())  # sleep time jitter
                self.logger.warning("%s: Retryable ClientError (%s). attempt=%d", self._name, err, attempt)
                time.sleep(sleep)
                attempt += 1
            except BotoCoreError as err:
                # Often transient network/serialization issues
                if attempt >= max_attempts:
                    raise
                # Compute exponential backoff with jitter
                sleep = base_sleep * (2 ** (attempt - 1))
                sleep = sleep * (0.5 + random.random())
                self.logger.warning("%s: Retryable BotoCoreError (%s). attempt=%d", self._name, err, attempt)
                time.sleep(sleep)
                attempt += 1

    def get_obj_key_for_reservation(self, reservation_id: str) -> str:
        """
        Helper method to construct the S3 object key for a given reservation ID.
        :param reservation_id: The ID of the reservation
        :return: The corresponding S3 object key
        """
        return f"{self.prefix}{reservation_id}.json"

    def add_reservations(self, reservations_dict: Dict[Reservation, Any],
                         source: str = None):
        """
        Add reservations to S3 storage.

        On-disk JSON schema written per reservation
        (key = "<prefix><reservation_id>.json"):

            {
                "name":       <str>,    # Authored network name (HOCON "name")
                "llm_config": <dict>,   # Optional LLM settings
                "tools":      <list>,   # Agent definitions making up the network
                ...                     # Any other top-level spec fields
                "metadata": {
                    ...                                          # User-authored keys (merged in)
                    "reservation": {                    # Injected by this method
                        "id":                          <str>,    # "<prefix>-<uuid4>"
                        "lifetime_in_seconds":         <float>,  # Lease duration
                        "expiration_time_in_seconds":  <float>,  # Wall-clock deadline
                    },
                    "stored_at": <float>,                        # time.time() at write
                }
            }

        Notes:
          * User-authored metadata keys (e.g. "description", "tags") are
            preserved; this method merges into agent_spec["metadata"]
            rather than replacing it.
          * lifetime_in_seconds:        client-requested duration.
          * expiration_time_in_seconds: now + min(lifetime, server max);
                                        Unix timestamp the system enforces against.
          * stored_at:                  time.time() at write; useful for
                                        clock-skew audit and orphan detection.

        :param reservations_dict: A mapping of Reservation -> some deployable agent spec
        :param source: A string describing where the deployment was coming from
        """
        self.logger.info("%s: Adding %d reservations to S3", self._name, len(reservations_dict))

        # Process each reservation/agent spec pair individually
        reservation: Reservation = None
        agent_spec: Dict[str, Any] = None
        for reservation, agent_spec in reservations_dict.items():

            # Build complete data structure containing reservation metadata,
            # the associated agent_spec, source information, and storage timestamp
            current_time: float = time.time()
            new_metadata: Dict[str, Any] = {
                "reservation": self.converter.to_dict(reservation),  # Serialized reservation object
                "stored_at": current_time              # When stored in S3
            }
            if agent_spec.get("metadata") is None:
                agent_spec["metadata"] = {}
            agent_spec["metadata"].update(new_metadata)

            # Generate S3 key using prefix and reservation ID for easy lookup
            reservation_id: str = reservation.get_reservation_id()
            key: str = self.get_obj_key_for_reservation(reservation_id)

            # Store as JSON object in S3 with proper content type
            json_body: str = dumps(agent_spec, indent=4)  # Pretty-printed JSON

            put_function = partial(self.s3_client.put_object,
                                   Bucket=self.bucket_name,
                                   Key=key,
                                   Body=json_body,
                                   ContentType="application/json")
            self._do_with_retries(put_function)

            self.logger.debug("%s: Successfully stored reservation %s in S3", self._name, reservation_id)

    def _retrieve_object_with_retries(self, obj_key: str) -> Dict[str, Any]:
        """
        Helper method to retrieve an S3 object with retries.
        :param obj_key: S3 object key to retrieve
        :return: The parsed JSON content of the S3 object as a dictionary
        :raises: ClientError if the object cannot be retrieved after retries
                 JSONDecodeError if the content cannot be parsed as JSON
        """
        get_function = partial(self.s3_client.get_object, Bucket=self.bucket_name, Key=obj_key)
        obj_response: Dict[str, Any] = self._do_with_retries(get_function)
        # Parse JSON content from S3 object body
        json_content: str = obj_response["Body"].read().decode("utf-8")
        return loads(json_content)

    def get_one_reservation(self, obj_key: str) -> Tuple[Reservation, Any]:
        """
        Sync a single reservation from S3.

        :param obj_key: reservation ID to retrieve (used to construct S3 object key)
        :return: Tuple of (reservation, agent_spec) if successful and not expired,
                 (None, None) otherwise
        """
        reservation: Reservation = None
        agent_network: AgentNetwork = None
        # Construct the S3 object key for this reservation ID
        s3_obj_key: str = self.get_obj_key_for_reservation(obj_key)
        try:
            # Retrieve the reservation object from S3
            agent_spec: Dict[str, Any] = self._retrieve_object_with_retries(s3_obj_key)
            metadata: Dict[str, Any] = agent_spec.get("metadata")

            # Reconstruct the Reservation object from stored dictionary
            reservation_dict: Dict[str, Any] = metadata.get("reservation")
            reservation = self.converter.from_dict(reservation_dict)
            # Reconstruct the AgentNetwork object using the agent spec dictionary
            # and reservation ID - which is our agent name in this design
            agent_network: AgentNetwork = AgentNetwork(agent_spec, reservation.get_reservation_id())

            self.logger.debug("%s: Successfully synced active reservation %s",
                              self._name, reservation.get_reservation_id())

        except ClientError as exception:
            # Handle case where another process already removed the object before we could read it
            if exception.response["Error"]["Code"] == "NoSuchKey":
                self.logger.debug("%s: Reservation %s was already removed by another process during sync",
                                  self._name, obj_key)
            else:
                # Log other S3 errors but don't raise - allows sync to continue
                self.logger.error("%s: S3 error processing reservation object %s during sync: %s",
                                  self._name, obj_key, str(exception))

        except JSONDecodeError as exception:
            # Log JSON errors but don't raise - allows sync to continue
            self.logger.error("%s: JSON error processing reservation object %s during sync: %s",
                              self._name, obj_key, str(exception))

        return reservation, agent_network

    def expire_one_reservation(self, obj_key: str, current_time: float) -> bool:
        """
        Check and expire a single reservation if it's expired.

        :param obj_key: S3 object key for the reservation
        :param current_time: Current timestamp to compare against
        :return: True if reservation was expired and deleted, False otherwise
        """
        expired: bool = False
        try:
            # Retrieve the reservation object from S3
            agent_spec: Dict[str, Any] = self._retrieve_object_with_retries(obj_key)
            metadata: Dict[str, Any] = agent_spec.get("metadata")
            reservation_data: Dict[str, Any] = metadata.get("reservation")

            # Compare current time against reservation's expiration timestamp
            expiration_time: float = reservation_data.get("expiration_time_in_seconds")
            if current_time > expiration_time:
                # Reservation has expired - remove it from S3 storage
                try:
                    delete_function = partial(self.s3_client.delete_object, Bucket=self.bucket_name, Key=obj_key)
                    self._do_with_retries(delete_function)
                    reservation_id: str = reservation_data.get("id")
                    self.logger.debug("%s: Deleted expired reservation %s from S3", self._name, reservation_id)
                    expired = True
                except ClientError as delete_error:
                    # Handle case where another process already deleted the object
                    if delete_error.response["Error"]["Code"] != "NoSuchKey":
                        # Re-raise other delete errors
                        raise delete_error

                    self.logger.debug("%s: Reservation %s was already deleted by another process", self._name, obj_key)
                    expired = True  # Consider this a successful expiration

            # Reservation is still active - no action needed

        except ClientError as exception:
            # Handle case where another process already removed the object before we could read it
            if exception.response["Error"]["Code"] == "NoSuchKey":
                self.logger.debug("%s: Reservation %s was already removed by another process", self._name, obj_key)
                expired = True  # Object is gone, which is the desired outcome for expiration
            else:
                # Log other S3 errors but don't raise - allows expiration to continue
                self.logger.error("%s: S3 error processing reservation object %s: %s",
                                  self._name, obj_key, str(exception))

        except JSONDecodeError as exception:
            # Log JSON errors but don't raise - allows expiration process to continue
            self.logger.error("%s: JSON error processing reservation object %s during expire: %s",
                              self._name, obj_key, str(exception))

        return expired

    def iter_reservation_keys(self) -> Iterable[str]:
        """
        Lists ALL objects under the current S3 bucket prefix and yields their
        object keys.

        Pages through results by calling list_objects_v2 directly with
        ContinuationToken rather than using a boto3 Paginator. Each
        list_objects_v2 call is a single, eager HTTP request, so wrapping it
        in _do_with_retries gives correct per-page retry semantics for
        transient ClientError/BotoCoreError: each page fetch is retried in
        isolation, and the ContinuationToken from the previous successful
        response is only consulted after that response has actually arrived.
        """
        continuation_token = None
        while True:
            kwargs = {
                "Bucket": self.bucket_name,
                "Prefix": self.prefix,
                "MaxKeys": self.max_keys_per_page,
            }
            if continuation_token:
                kwargs["ContinuationToken"] = continuation_token
            response = self._do_with_retries(
                partial(self.s3_client.list_objects_v2, **kwargs)
            )
            for obj in response.get("Contents", []):
                yield obj["Key"]
            if not response.get("IsTruncated"):
                # This was the last page - exit loop
                break
            continuation_token = response["NextContinuationToken"]

    def expire_reservations(self):
        """
        Remove expired reservations from S3 storage.
        """
        self.logger.debug("%s: Starting expiration process for S3 reservations", self._name)

        # Track how many reservations we expire for reporting
        expired_count: int = 0
        # Get current timestamp once for consistent expiration checking
        current_time: float = time.time()

        for reservation_key in self.iter_reservation_keys():
            # Attempt to expire this reservation and increment counter if successful
            if self.expire_one_reservation(reservation_key, current_time):
                expired_count += 1

        if expired_count > 0:
            self.logger.info("%s: Expiration complete: removed %d expired reservations from S3",
                             self._name, expired_count)
        else:
            self.logger.debug("%s: Expiration complete: removed no expired reservations from S3", self._name)
