
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
from typing import Optional
from typing import Tuple

from functools import partial
from json.decoder import JSONDecodeError
from logging import getLogger
from logging import Logger

from botocore.exceptions import ClientError

from neuro_san.interfaces.reservation import Reservation
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.reservations.reservation_dictionary_converter import ReservationDictionaryConverter
from neuro_san.service.watcher.temp_networks.s3.aws_sync_client_worker import AwsSyncClientWorker
from neuro_san.service.watcher.temp_networks.s3.s3_reservations_retriever import S3ReservationsRetriever
from neuro_san.service.watcher.temp_networks.s3.s3_util import S3Util


class S3ReservationsReader:
    """
    Handles reading of Reservations from AWS S3.

    The main entry point here is get_one_reservation(), which eventually gets called from
    ExpiringAgentNetworkStorage.get_agent_network_provider() as part of a request query.
    """

    def __init__(self, name: str = "S3ReservationsReader", bucket_name: str = "",
                 prefix: str = S3Util.DEFAULT_RESERVATIONS_PREFIX):
        """
        Initialize the S3 reservations reader.

        :param bucket_name: S3 bucket name (defaults to AGENT_RESERVATIONS_S3_BUCKET env var)
        :param prefix: S3 key prefix for reservation objects
        """
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

    def get_one_reservation(self, reservation_id: str) -> Tuple[Optional[Reservation], Optional[AgentNetwork]]:
        """
        Sync a single reservation from S3.

        :param reservation_id: Reservation ID to retrieve (used to construct S3 object key)
        :return: Tuple of (reservation, agent_network) if successful and not expired,
                 (None, None) otherwise
        """
        reservation: Reservation = None
        agent_network: AgentNetwork = None

        # Construct the S3 object key for this reservation ID
        s3_obj_key: str = S3Util.get_obj_key_for_reservation(self.retriever.get_prefix(), reservation_id)

        client_worker: AwsSyncClientWorker = self.retriever.get_sync_client_worker()
        get_function: Callable = partial(self.retriever.retrieve_object_with_retries,
                                         obj_key=s3_obj_key, source=self.name)

        try:
            # Retrieve the reservation object from S3. The parsed body can be
            # any JSON type (not just a dict) - extract_reservation_data()
            # below is designed to accept and validate exactly that.
            agent_spec: Any = client_worker.retry_with_new_client(get_function)

            # Validate the payload shape BEFORE constructing any objects, using
            # the same policy as the expiration sweep
            # (see S3Util.extract_reservation_data).
            #
            # Checking the constructed object afterwards does not work:
            # ReservationDictionaryConverter.from_dict() unconditionally returns
            # an AgentReservation instance - truthy even when built from {} -
            # so a post-construction "if not reservation:" can never fire, and
            # the bogus reservation's expiration_time_in_seconds of None would
            # later crash ExpiringAgentNetworkStorage.is_expired() on the
            # request path with
            # "'>' not supported between instances of 'float' and 'NoneType'".
            # Validating the raw dict here is the one reliable place to detect
            # malformed payloads and treat them as not-found.
            reservation_dict: Optional[Dict[str, Any]] = S3Util.extract_reservation_data(agent_spec)
            if reservation_dict is None:
                # Log when we get malformed content on read (for request)
                self.logger.error("%s: Failed to parse reservation payload for %s", self.name, reservation_id)
                return None, None

            # Reconstruct the Reservation object from stored dictionary
            reservation = self.converter.from_dict(reservation_dict)

            # Reconstruct the AgentNetwork object using the agent spec dictionary
            # and reservation ID - which is our agent name in this design
            agent_network: AgentNetwork = AgentNetwork(agent_spec, reservation.get_reservation_id())

            self.logger.debug("%s: Successfully synced active reservation %s",
                              self.name, reservation.get_reservation_id())

        except ClientError as exception:
            # Handle case where another process already removed the object before we could read it.
            # get_error_code() is used instead of raw response indexing, which can
            # KeyError/TypeError on responses without a parsed Error dict
            # (see S3Util.get_error_code for details).
            if S3Util.get_error_code(exception) == "NoSuchKey":
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
