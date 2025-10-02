# All Rights Reserved.
# Issued under the Academic Public License.
#
# You can be released from the terms, and requirements of the Academic Public
# License by purchasing a commercial license.
# Purchase of a commercial license is mandatory for any use of the
# neuro-san SDK Software in commercial settings.
#
# END COPYRIGHT

from typing import Any
from typing import Dict
from typing import Tuple

import os
import time

from json import dumps
from json import loads
from json.decoder import JSONDecodeError
from logging import getLogger
from logging import Logger

from boto3 import client as boto3_client
from botocore.client import BaseClient
from botocore.exceptions import ClientError
from botocore.exceptions import NoCredentialsError

from neuro_san.interfaces.reservation import Reservation
from neuro_san.internals.interfaces.reservations_storage import ReservationsStorage
from neuro_san.service.watcher.interfaces.startable import Startable
from neuro_san.service.watcher.temp_networks.reservation_dictionary_converter import ReservationDictionaryConverter


class S3ReservationsStorage(ReservationsStorage, Startable):
    """
    AWS S3-based implementation of ReservationsStorage.

    Stores reservations as JSON objects in an S3 bucket, with each reservation
    stored in its associated agent spec as metadata.
    """

    def __init__(self, bucket_name: str = "", prefix: str = "reservations/"):
        """
        Initialize S3 reservations storage.

        :param bucket_name: S3 bucket name (defaults to AGENT_RESERVATIONS_S3_BUCKET env var)
        :param prefix: S3 key prefix for reservation objects
        """
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
        self.sync_target: ReservationsStorage = None
        self.s3_client: BaseClient = None

        # Track last sync timestamp for incremental syncing (0.0 means sync all)
        self.last_sync_timestamp: float = 0.0
        self.converter = ReservationDictionaryConverter()

        self.logger: Logger = getLogger(self.__class__.__name__)

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
            self.logger.info("Successfully connected to S3 bucket: %s", self.bucket_name)

        except NoCredentialsError as exception:
            # Handle missing AWS credentials
            raise ValueError("AWS credentials not found. Please configure AWS credentials.") from exception
        except ClientError as exception:
            # Handle various S3 access errors with specific messages
            error_code: str = exception.response["Error"]["Code"]
            if error_code == "404":
                raise ValueError(f"S3 bucket '{self.bucket_name}' does not exist") from exception
            if error_code == "403":
                raise ValueError(f"Access denied to S3 bucket '{self.bucket_name}'") from exception
            raise ValueError(f"Error accessing S3 bucket '{self.bucket_name}': {exception}") from exception

    def set_sync_target(self, sync_target: ReservationsStorage):
        """
        Set the sync target for this storage implementation.

        :param sync_target: The ReservationsStorage where in-memory versions end up
        """
        # Store reference to the target storage for syncing operations
        # This allows S3 storage to push reservations to in-memory or other storage types
        self.sync_target = sync_target

    def add_reservations(self, reservations_dict: Dict[Reservation, Any],
                         source: str = None):
        """
        Add reservations to S3 storage.

        :param reservations_dict: A mapping of Reservation -> some deployable agent spec
        :param source: A string describing where the deployment was coming from
        """
        self.logger.info("Adding %d reservations to S3", len(reservations_dict))

        # Process each reservation/agent spec pair individually
        reservation: Reservation = None
        agent_spec: Dict[str, Any] = None
        for reservation, agent_spec in reservations_dict.items():

            # Build complete data structure containing reservation metadata,
            # the associated agent_spec, source information, and storage timestamp
            current_time: float = time.time()
            agent_spec["metadata"] = {
                "reservation": self.converter.to_dict(reservation),  # Serialized reservation object
                "stored_at": current_time              # When stored in S3
            }

            # Generate S3 key using prefix and reservation ID for easy lookup
            reservation_id: str = reservation.get_reservation_id()
            key: str = f"{self.prefix}{reservation_id}.json"

            # Store as JSON object in S3 with proper content type
            json_body: str = dumps(agent_spec, indent=4)  # Pretty-printed JSON
            self.s3_client.put_object(
                Bucket=self.bucket_name,
                Key=key,
                Body=json_body,
                ContentType="application/json"
            )

            self.logger.debug("Successfully stored reservation %s in S3", reservation_id)

    def sync_one_reservation(self, obj_key: str) -> Tuple[Reservation, Any]:
        """
        Sync a single reservation from S3.

        :param obj_key: S3 object key for the reservation
        :return: Tuple of (reservation, agent_spec) if successful and not expired,
                 (None, None) otherwise
        """
        reservation: Reservation = None
        agent_spec: Dict[str, Any] = None
        try:
            # Retrieve the reservation object from S3
            obj_response: Dict[str, Any] = self.s3_client.get_object(
                Bucket=self.bucket_name,
                Key=obj_key
            )

            # Parse JSON content from S3 object body
            json_content: str = obj_response["Body"].read().decode("utf-8")
            agent_spec: Dict[str, Any] = loads(json_content)
            metadata: Dict[str, Any] = agent_spec.get("metadata")

            # Reconstruct the Reservation object from stored dictionary
            reservation_dict: Dict[str, Any] = metadata.get("reservation")
            reservation = self.converter.from_dict(reservation_dict)

            self.logger.debug("Successfully synced active reservation %s",
                              reservation.get_reservation_id())

        except ClientError as exception:
            # Handle case where another process already removed the object before we could read it
            if exception.response["Error"]["Code"] == "NoSuchKey":
                self.logger.debug("Reservation %s was already removed by another process during sync",
                                  obj_key)
            else:
                # Log other S3 errors but don't raise - allows sync to continue
                self.logger.error("S3 error processing reservation object %s during sync: %s",
                                  obj_key, str(exception))

        except JSONDecodeError as exception:
            # Log JSON errors but don't raise - allows sync to continue
            self.logger.error("JSON error processing reservation object %s during sync: %s",
                              obj_key, str(exception))

        return reservation, agent_spec

    def sync_reservations(self):
        """
        Sync reservations from S3 to the sync target (if set).
        Only syncs objects modified after the last sync timestamp for efficiency.
        """
        # Validate that a sync target has been configured
        if not self.sync_target:
            self.logger.warning("No sync target set, skipping sync operation")
            return

        sync_start_time: float = time.time()

        if self.last_sync_timestamp > 0.0:
            self.logger.debug("Starting incremental sync from S3 (since %s)",
                              time.ctime(self.last_sync_timestamp))
        else:
            self.logger.debug("Starting full sync operation from S3 to configured sync target")

        # List all reservation objects in S3 bucket with our prefix
        response: Dict[str, Any] = self.s3_client.list_objects_v2(
            Bucket=self.bucket_name,
            Prefix=self.prefix
        )

        # Handle case where no reservations exist in S3
        if "Contents" not in response:
            self.logger.debug("No reservations found in S3 bucket")
            # Update sync timestamp even if no objects found
            self.last_sync_timestamp = sync_start_time
            return

        # Build dictionary of active reservations to sync
        reservations_dict: Dict[Reservation, Any] = {}
        processed_count: int = 0
        skipped_count: int = 0

        # Process each S3 object individually using our helper method
        obj: Dict[str, Any]
        for obj in response["Contents"]:
            # Skip objects that haven't been modified since last sync
            if self.last_sync_timestamp > 0.0:
                obj_modified_time: float = obj["LastModified"].timestamp()
                if obj_modified_time <= self.last_sync_timestamp:
                    skipped_count += 1
                    continue

            processed_count += 1
            reservation: Reservation = None
            agent_spec: Dict[str, Any] = None
            reservation, agent_spec = self.sync_one_reservation(obj["Key"])
            if reservation is None or agent_spec is None:
                # Skip anything that had an error associated with it
                continue

            # Only include successfully processed, non-expired reservations (skip empty ones)
            if reservation.get_reservation_id() != "" and agent_spec != {}:
                reservations_dict[reservation] = agent_spec

        # Push collected reservations to the sync target storage
        if reservations_dict:
            self.sync_target.add_reservations(reservations_dict)
            self.logger.info("Successfully synced %d active reservations to target " +
                             "(processed %d, skipped %d unchanged objects)",
                             len(reservations_dict), processed_count, skipped_count)
        else:
            if processed_count > 0:
                self.logger.debug(
                    "No active reservations found to sync (processed %d, skipped %d unchanged objects)",
                    processed_count, skipped_count)
            else:
                self.logger.debug("No new objects to sync (skipped %d unchanged objects)", skipped_count)

        # Update the last sync timestamp to mark successful completion
        self.last_sync_timestamp = sync_start_time

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
            obj_response: Dict[str, Any] = self.s3_client.get_object(
                Bucket=self.bucket_name,
                Key=obj_key
            )

            # Parse JSON content to extract reservation metadata
            json_content: str = obj_response["Body"].read().decode("utf-8")
            agent_spec: Dict[str, Any] = loads(json_content)
            metadata: Dict[str, Any] = agent_spec.get("metadata")
            reservation_data: Dict[str, Any] = metadata.get("reservation")

            # Compare current time against reservation's expiration timestamp
            expiration_time: float = reservation_data.get("expiration_time_in_seconds")
            if current_time > expiration_time:
                # Reservation has expired - remove it from S3 storage
                try:
                    self.s3_client.delete_object(
                        Bucket=self.bucket_name,
                        Key=obj_key
                    )
                    reservation_id: str = reservation_data.get("id")
                    self.logger.debug("Deleted expired reservation %s from S3", reservation_id)
                    expired = True
                except ClientError as delete_error:
                    # Handle case where another process already deleted the object
                    if delete_error.response["Error"]["Code"] != "NoSuchKey":
                        # Re-raise other delete errors
                        raise delete_error

                    self.logger.debug("Reservation %s was already deleted by another process", obj_key)
                    expired = True  # Consider this a successful expiration

            # Reservation is still active - no action needed

        except ClientError as exception:
            # Handle case where another process already removed the object before we could read it
            if exception.response["Error"]["Code"] == "NoSuchKey":
                self.logger.debug("Reservation %s was already removed by another process", obj_key)
                expired = True  # Object is gone, which is the desired outcome for expiration
            else:
                # Log other S3 errors but don't raise - allows expiration to continue
                self.logger.error("S3 error processing reservation object %s: %s", obj_key, str(exception))

        except JSONDecodeError as exception:
            # Log JSON errors but don't raise - allows expire to continue
            self.logger.error("JSON error processing reservation object %s during expire: %s",
                              obj_key, str(exception))

        return expired

    def expire_reservations(self):
        """
        Remove expired reservations from S3 storage.
        """
        self.logger.debug("Starting expiration process for S3 reservations")

        # List all reservation objects in S3 bucket with our prefix
        response: Dict[str, Any] = self.s3_client.list_objects_v2(
            Bucket=self.bucket_name,
            Prefix=self.prefix
        )

        # Handle case where no reservations exist in S3
        if "Contents" not in response:
            self.logger.debug("No reservations found in S3 bucket for expiration")
            return

        # Track how many reservations we expire for reporting
        expired_count: int = 0
        # Get current timestamp once for consistent expiration checking
        current_time: float = time.time()

        # Process each S3 object individually using our helper method
        obj: Dict[str, Any]
        for obj in response["Contents"]:
            # Attempt to expire this reservation and increment counter if successful
            if self.expire_one_reservation(obj["Key"], current_time):
                expired_count += 1

        if expired_count > 0:
            self.logger.info("Expiration complete: removed %d expired reservations from S3", expired_count)
        else:
            self.logger.debug("Expiration complete: removed no expired reservations from S3")
