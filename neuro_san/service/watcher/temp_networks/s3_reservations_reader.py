
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
from typing import Tuple

from json.decoder import JSONDecodeError
from logging import getLogger
from logging import Logger

from botocore.exceptions import ClientError

from neuro_san.interfaces.reservation import Reservation
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.reservations.reservation_dictionary_converter import ReservationDictionaryConverter
from neuro_san.service.watcher.temp_networks.s3_reservations_retriever import S3ReservationsRetriever
from neuro_san.service.watcher.temp_networks.s3_retry_util import S3RetryUtil


class S3ReservationsReader:
    """
    Handles reading of Reservations from AWS S3.

    The main entry point here is get_one_reservation(), which eventually gets called from
    ExpiringAgentNetworkStorage.get_agent_network_provider() as part of a request query.
    """

    def __init__(self, name: str = "S3ReservationsReader", bucket_name: str = "", prefix: str = "reservations/"):
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
        self.logger: Logger = getLogger(self.__class__.__name__)
        self.name: str = name

        self.retriever = S3ReservationsRetriever(name=self.name, bucket_name=bucket_name, prefix=prefix)
        self.converter = ReservationDictionaryConverter()

    def start(self):
        """
        Initialize the S3 client and validate connection to the bucket.

        This method can be called to re-initialize the connection if needed.
        """
        self.retriever.start()

    def get_one_reservation(self, obj_key: str) -> Tuple[Reservation, Any]:
        """
        Sync a single reservation from S3.

        :param reservation_id: reservation ID to retrieve (used to construct S3 object key)
        :return: Tuple of (reservation, agent_spec) if successful and not expired,
                 (None, None) otherwise
        """
        reservation_id: str = obj_key
        reservation: Reservation = None
        agent_network: AgentNetwork = None
        # Construct the S3 object key for this reservation ID
        s3_obj_key: str = S3RetryUtil.get_obj_key_for_reservation(self.retriever.get_prefix(), reservation_id)
        try:
            # Retrieve the reservation object from S3
            agent_spec: Dict[str, Any] = self.retriever.retrieve_object_with_retries(s3_obj_key)
            metadata: Dict[str, Any] = agent_spec.get("metadata")

            # Reconstruct the Reservation object from stored dictionary
            reservation_dict: Dict[str, Any] = metadata.get("reservation")
            reservation = self.converter.from_dict(reservation_dict)
            # Reconstruct the AgentNetwork object using the agent spec dictionary
            # and reservation ID - which is our agent name in this design
            agent_network: AgentNetwork = AgentNetwork(agent_spec, reservation.get_reservation_id())

            self.logger.debug("%s: Successfully synced active reservation %s",
                              self.name, reservation.get_reservation_id())

        except ClientError as exception:
            # Handle case where another process already removed the object before we could read it
            if exception.response["Error"]["Code"] == "NoSuchKey":
                self.logger.debug("%s: Reservation %s was already removed by another process during sync",
                                  self.name, reservation_id)
            else:
                # Log other S3 errors but don't raise - allows sync to continue
                self.logger.error("%s: S3 error processing reservation object %s during sync: %s",
                                  self.name, reservation_id, str(exception))

        except JSONDecodeError as exception:
            # Log JSON errors but don't raise - allows sync to continue
            self.logger.error("%s: JSON error processing reservation object %s during sync: %s",
                              self.name, reservation_id, str(exception))

        return reservation, agent_network
