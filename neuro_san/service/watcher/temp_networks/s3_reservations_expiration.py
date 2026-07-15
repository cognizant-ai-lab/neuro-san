
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

from time import time
from functools import partial

from json.decoder import JSONDecodeError
from logging import getLogger
from logging import Logger

from botocore.client import BaseClient
from botocore.exceptions import ClientError

from leaf_common.parsers.dictionary_extractor import DictionaryExtractor

from neuro_san.service.watcher.temp_networks.aws_sync_client_worker import AwsSyncClientWorker
from neuro_san.service.watcher.temp_networks.s3_reservations_retriever import S3ReservationsRetriever
from neuro_san.service.watcher.temp_networks.s3_util import S3Util


class S3ReservationsExpiration:
    """
    Handles expiration of Reservations from S3 storage.

    The main entry point to this guy is expire_reservations() which gets called as part of
    S3ReservationsStorage watcher loop.
    """

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
        Initialize the S3 client and validate connection to the bucket.

        This method can be called to re-initialize the connection if needed.
        """
        self.retriever.start()

    def expire_reservations(self):
        """
        Remove expired reservations from S3 storage.
        """
        self.logger.debug("%s: Starting expiration process for S3 reservations", self.name)

        expire_function = partial(self.expire_any_reservations)

        client_worker: AwsSyncClientWorker = self.retriever.get_sync_client_worker()
        client_worker.do_work_with_new_client(expire_function)

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
            if self.expire_one_reservation(reservation_key, current_time, sync_aws_client):
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

            list_objects_function = partial(sync_aws_client.list_objects_v2, **kwargs)
            response = client_worker.do_with_retries(self.name, list_objects_function)
            if response is None:
                response = {}
            for obj in response.get("Contents", []):
                yield obj.get("Key")
            if not response.get("IsTruncated"):
                # This was the last page - exit loop
                break
            continuation_token = response.get("NextContinuationToken")

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

        empty: Dict[str, Any] = {}
        expired: bool = False
        try:
            # Retrieve the reservation object from S3
            agent_spec: Dict[str, Any] = self.retriever.retrieve_object_with_retries(obj_key)
            if agent_spec is None:
                agent_spec = empty

            extractor = DictionaryExtractor(agent_spec)
            reservation_data: Dict[str, Any] = extractor.get("metadata.reservation", empty)

            client_worker: AwsSyncClientWorker = self.retriever.get_sync_client_worker()

            # Compare current time against reservation's expiration timestamp
            expiration_time: float = reservation_data.get("expiration_time_in_seconds", 0)
            if current_time > expiration_time:
                # Reservation has expired - remove it from S3 storage
                try:
                    delete_function = partial(sync_aws_client.delete_object,
                                              Bucket=self.retriever.get_bucket_name(),
                                              Key=obj_key)
                    client_worker.do_with_retries(source, delete_function)
                    reservation_id: str = reservation_data.get("id", "<unknown>")
                    self.logger.debug("%s: Deleted expired reservation %s from S3", self.name, reservation_id)
                    expired = True
                except ClientError as delete_error:
                    extractor = DictionaryExtractor(delete_error.response)
                    # Handle case where another process already deleted the object
                    if extractor.get("Error.Code") != "NoSuchKey":
                        # Re-raise other delete errors
                        raise delete_error

                    self.logger.debug("%s: Reservation %s was already deleted by another process", self.name, obj_key)
                    expired = True  # Consider this a successful expiration

            # Reservation is still active - no action needed

        except ClientError as exception:
            # Handle case where another process already removed the object before we could read it
            extractor = DictionaryExtractor(exception.response)
            if extractor.get("Error.Code") == "NoSuchKey":
                self.logger.debug("%s: Reservation %s was already removed by another process", self.name, obj_key)
                expired = True  # Object is gone, which is the desired outcome for expiration
            else:
                # Log other S3 errors but don't raise - allows expiration to continue
                self.logger.error("%s: S3 error processing reservation object %s: %s",
                                  self.name, obj_key, str(exception))

        except JSONDecodeError as exception:
            # Log JSON errors but don't raise - allows expiration process to continue
            self.logger.error("%s: JSON error processing reservation object %s during expire: %s",
                              self.name, obj_key, str(exception))

        return expired
