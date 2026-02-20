
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


class ReservationsStorage:
    """
    An interface for implementations of Reservations storage
    """

    def set_sync_target(self, sync_target: ReservationsStorage):
        """
        :param sync_target: The ReservationsStorage where in-memory versions end up
        """
        raise NotImplementedError

    def add_reservations(self, reservations_dict: Dict[Reservation, Any],
                         source: str = None):
        """
        Add a set of reservations for agent networks en-masse

        :param reservations_dict: A mapping of Reservation -> some deployable entity
        :param source: A string describing where the deployment was coming from
        """
        raise NotImplementedError

    def sync_reservations(self):
        """
        Sync Reservations with some underlying data source
        """
        raise NotImplementedError

    def expire_reservations(self):
        """
        Remove Reservations that are expired
        """
        raise NotImplementedError
