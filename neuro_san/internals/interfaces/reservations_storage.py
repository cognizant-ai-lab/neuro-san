# Copyright (C) 2023-2025 Cognizant Digital Business, Evolutionary AI.
# All Rights Reserved.
# Issued under the Academic Public License.
#
# You can be released from the terms, and requirements of the Academic Public
# License by purchasing a commercial license.
# Purchase of a commercial license is mandatory for any use of the
# neuro-san SDK Software in commercial settings.
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
