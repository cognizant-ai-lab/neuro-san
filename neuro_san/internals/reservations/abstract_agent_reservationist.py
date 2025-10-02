
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
from typing import Any
from typing import Dict
from typing import Set
from typing import Union

from asyncio import Event
from time import time

from neuro_san.interfaces.reservation import Reservation
from neuro_san.interfaces.reservationist import Reservationist
from neuro_san.internals.interfaces.reservations_storage import ReservationsStorage
from neuro_san.internals.reservations.agent_reservation import AgentReservation


class AbstractAgentReservationist(Reservationist):
    """
    Reservationist implementation that allows procurement of agent ids
    for a specific amount of time for direct sessions only.
    """

    def __init__(self, reservations_storage: Set[ReservationsStorage],
                 max_lifetime_in_seconds: float = Reservationist.DEFAULT_LIFETIME):
        """
        Constructor

        :param reservations_storage: A Set of ReservationsStorage instances that manage
                            any temporary networks
        :param max_lifetime_in_seconds: The maximum lifetime allowed for any Reservation.
        """
        self.reservations_storage: Set[ReservationsStorage] = reservations_storage
        self.max_lifetime_in_seconds: float = max_lifetime_in_seconds

    async def reserve(self, lifetime_in_seconds: float = Reservationist.DEFAULT_LIFETIME,
                      prefix: str = "") -> Reservation:
        """
        Creates a reservation for a specific time period.

        :param lifetime_in_seconds: The lifetime of the reservation
        :param prefix: A string prefix to prepend to the id so as to provide external context.
        :return: A new Reservation object corresponding to the request.
        """
        actual_lifetime: float = min(lifetime_in_seconds, self.max_lifetime_in_seconds)
        reservation = AgentReservation(actual_lifetime, prefix=prefix)
        return reservation

    async def deploy(self,
                     deployment_dict: Dict[Reservation,
                                           Dict[Union[str, Event],
                                                Dict[AgentReservation,
                                                     Dict[str, Any]]]],
                     confirmation: bool = False) -> Event:
        """
        Deploy multiple Reservations.

        :param deployment_dict: A dictionary whose keys are Reservation objects
                    previously obtained with reserve() and whose values are each an
                    object to deploy using the key as Reservation.
                    In this case, the object value to deploy is another dictionary where:
                        keys can be either a string or an asyncio.Event
                        values are a dictionary of AgentReservations -> agent_spec dictionaries
                            That is, these values are deployment_dicts from an AccumulatingAgentReservationist.
        :param confirmation: When True, indicates a confirmation Event is desired.
                            When False (the default), no such confirmation is needed.
                            This is ignored on this instance
        :return: Either a confiramtion Event object whose wait() method will confirm
                that the deployment is complete, or None, depending on the value passed
                for confirmation.
                This instance always returns None.
        """
        raise NotImplementedError

    @staticmethod
    async def set_event(event: Event):
        """
        :param event: The event to set
        """
        event.set()

    def deploy_together(self, deployment_dict: Dict[AgentReservation, Dict[str, Any]],
                        source: str,
                        max_lifetime_in_seconds: float):
        """
        :param deployment_dict: A dictionary whose keys are AgentReservations
                            and whose values are agent network spec dictionaries.
        :param source: A string describing where the deployment was coming from
        :param max_lifetime_in_seconds: Longest a temp network can live
        """
        # Get a timestamp as a basis of coordinated expiration.
        use_now: float = time()

        reservations_dict: Dict[Reservation, Dict[str, Any]] = {}
        for reservation, agent_spec in deployment_dict.items():

            # For each reservation in the block, set a consistent expiration time
            reservation.set_expiration_from(use_now, max_lifetime_in_seconds)

            # Put together a dictionary of reservations -> agent specs
            reservations_dict[reservation] = agent_spec

        # Deploy locally.
        for storage in self.reservations_storage:
            # This can synchronously lock
            storage.add_reservations(reservations_dict, source)
