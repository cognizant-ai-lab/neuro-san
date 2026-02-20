
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
from __future__ import annotations

from typing import Any
from typing import Dict

from neuro_san.interfaces.reservation import Reservation


class ExpiringReservationsStorage:
    """
    An interface for implementations of basic Reservations storage,
    supporting addition Reservations in bulk and retrieval of individual Reservations,
    as well as expiration of Reservations based on their lifetime.
    """

    def add_reservations(self, reservations_dict: Dict[Reservation, Any],
                         source: str = None):
        """
        Add a set of reservations for agent networks en-masse

        :param reservations_dict: A mapping of Reservation -> some deployable entity
        :param source: A string describing where the deployment was coming from
        """
        raise NotImplementedError

    def get_one_reservation(self, obj_key: str) -> Tuple[Reservation, Any]:
        """
        Extract a single reservation.

        :param obj_key: unique key for the reservation
        :return: Tuple of (reservation, agent data) if successful
                 and reservation is not expired,
                 (None, None) otherwise
        """
        raise NotImplementedError

    def expire_reservations(self):
        """
        Remove Reservations that are expired
        """
        raise NotImplementedError

    def set_base_storage(self, base_storage: ExpiringReservationsStorage):
        """
        Set a "base" storage to use as a source of truth for reservations.
        This is optional, but if set, will be used as the source of truth for reservations
        and the implementing class will act as a cache in front of it.
        :param base_storage: An ExpiringReservationsStorage instance to use as a source of truth
        """
        raise NotImplementedError
