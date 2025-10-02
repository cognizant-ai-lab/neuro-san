
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

from uuid import uuid4

from os import environ

from neuro_san.interfaces.reservation import Reservation


class AgentReservation(Reservation):
    """
    A Reservation for an Agent (network).
    """

    def __init__(self, lifetime_in_seconds: float, prefix: str = ""):
        """
        Constructor

        :param lifetime_in_seconds: The number of seconds the reservation is allowed to exist.
        :param prefix: A string prefix to prepend to the id so as to provide external context.
        """
        super().__init__(lifetime_in_seconds)

        # Use a uuid. Add a prefix if one is provided
        self.id: str = str(uuid4())
        self.prefix: str = prefix
        if self.prefix is None:
            self.prefix = ""
        if len(self.prefix) > 0:
            self.prefix = f"{self.prefix}-"

    def get_reservation_id(self) -> str:
        """
        :return: The id associated with the reservation instance
        """
        return f"{self.prefix}{self.id}"

    def get_prefix(self) -> str:
        """
        :return: The prefix assigned at construct time
        """
        return self.prefix

    def get_url(self) -> str:
        """
        :return: A url associated with the reservation.
                 Can be None if this is not an option for what we are reserving.
        """
        # Start with a locally bound name.
        url: str = self.get_reservation_id()

        # See if we have an external agent name to tack on.
        external_url: str = environ.get("AGENT_EXTERNAL_SERVER_URL")
        if external_url is not None:

            # Remove any ending slashes to standardize
            while external_url.endswith("/"):
                external_url = external_url[:-1]

            # We still have something, so prepend on the external_url
            if len(external_url) > 0:
                # Assume always http for now.
                url = f"{external_url}/api/vl/{url}"

        return url

    def set_expiration_from(self, use_now_in_seconds: float,
                            max_lifetime_in_seconds: float):
        """
        Set the expiration time in seconds using the input as a basis for "now"..
        """
        actual_lifetime: float = min(self.get_lifetime_in_seconds(), max_lifetime_in_seconds)
        self.expiration_time_in_seconds = use_now_in_seconds + actual_lifetime
