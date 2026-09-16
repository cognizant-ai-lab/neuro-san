
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
from typing import Any
from typing import Dict
from typing import List
from typing import Tuple

from neuro_san.interfaces.reservation import Reservation
from neuro_san.internals.interfaces.reservations_storage import ReservationsStorage


class RecordingReservationsStorage(ReservationsStorage):
    """
    A test double for the "base" ReservationsStorage that ExpiringAgentNetworkStorage
    writes through to.  It records every add_reservations() call so tests can inspect
    exactly which agent specs would have been persisted to S3/local storage.
    """

    def __init__(self):
        """
        Constructor
        """
        # One entry per add_reservations() call, in call order.
        self.received: List[Dict[Reservation, Dict[str, Any]]] = []
        self.sources: List[str] = []

    async def add_reservations(self, reservations_dict: Dict[Reservation, Any],
                               source: str = None):
        """
        Records the reservations that would have been persisted.

        :param reservations_dict: A mapping of Reservation -> agent network spec
        :param source: A string describing where the deployment was coming from
        """
        self.received.append(reservations_dict)
        self.sources.append(source)

    def get_one_reservation(self, obj_key: str) -> Tuple[Reservation, Any]:
        """
        Always reports the reservation as absent; the tests using this double only
        exercise the write path.

        :param obj_key: unique key for the reservation
        :return: (None, None)
        """
        return None, None

    def expire_reservations(self):
        """
        Nothing to expire in this test double.
        """
