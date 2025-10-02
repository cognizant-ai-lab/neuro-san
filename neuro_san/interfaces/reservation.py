
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


class Reservation:
    """
    A data structure containing information about an id procured for a specific amount of time.
    """

    def __init__(self, lifetime_in_seconds: float):
        """
        Constructor

        :param lifetime_in_seconds: The number of seconds the reservation is allowed to exist.
        """
        # This id is to be assigned by the implementations however they see fit.
        # We recommend uuid4().
        self.id: str = None
        self.lifetime_in_seconds: float = lifetime_in_seconds
        self.expiration_time_in_seconds: float = 0.0

    def get_reservation_id(self) -> str:
        """
        :return: The id associated with the reservation instance
        """
        return self.id

    def get_lifetime_in_seconds(self) -> float:
        """
        :return: The lifetime in seconds associated with the reservation
        """
        return self.lifetime_in_seconds

    def get_expiration_time_in_seconds(self) -> float:
        """
        :return: The expiration time in seconds since the epoch, ala time.time().
        """
        return self.expiration_time_in_seconds

    def get_url(self) -> str:
        """
        :return: A url associated with the reservation.
                 Can be None if this is not an option for what we are reserving.
        """
        raise NotImplementedError
