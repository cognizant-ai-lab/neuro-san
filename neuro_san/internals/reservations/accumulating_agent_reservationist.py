
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
from typing import Union

from asyncio import Event

from neuro_san.interfaces.reservation import Reservation
from neuro_san.interfaces.reservationist import Reservationist
from neuro_san.internals.reservations.agent_reservation import AgentReservation


class AccumulatingAgentReservationist(Reservationist):
    """
    A Reservationist implementation that accumulates Reservations to be deployed later.
    This *must* be used within the context of a Python async(hronous) event loop.

    This object supports the asynchronous Python Context Manager protocol by implementing the
    __aenter__() and __aexit__() methods.

    We expect its use within a CodedTool's async_invoke() to be:

        reservationist: Reservationist = args.get("reservationist")

        # Creating Reservations can be done outside the with-statement
        reservation: Reservation = await reservationist.reserve()
        deployments: Dict[Reservation, Dict[str, Any]] = {
            reservation: my_agent_spec,
            ...
        }

        # Deploy the reservations with confirmation event
        deployed_event: asyncio.Event = None
        async with reservationist:
            deployed_event = await reservationist.deploy(deployments, confirmation=True)

        if deployed_event is not None:
            await deployed_event.wait()
    """

    def __init__(self, supporting_reservationist: Reservationist,
                 agent_name: str,
                 max_lifetime_in_seconds: float = Reservationist.DEFAULT_LIFETIME):
        """
        Constructor

        :param supporting_reservationist: The supporting Reservationist that will do the real work
        :param agent_name: The full name of the agent using this instance
        :param max_lifetime_in_seconds: The maximum lifetime allowed for any Reservation.
        """
        self.max_lifetime_in_seconds: float = max_lifetime_in_seconds
        self.agent_name: str = agent_name
        self.deployments: Dict[Union[Event, str], Dict[Reservation, Dict[str, Any]]] = {}
        self._supporting_reservationist: Reservationist = supporting_reservationist
        self._supporting_reservation: Reservation = None

    async def reserve(self, lifetime_in_seconds: float = Reservationist.DEFAULT_LIFETIME,
                      prefix: str = "") -> Reservation:
        """
        Creates a reservation for a specific time period.

        :param lifetime_in_seconds: The lifetime of the reservation
        :param prefix: A string prefix to prepend to the id so as to provide external context.
        :return: A new Reservation object corresponding to the request.
        """
        actual_lifetime: float = min(lifetime_in_seconds, self.max_lifetime_in_seconds)
        if prefix is not None and len(prefix) > 0:
            self.verify_id(prefix)
        reservation = AgentReservation(actual_lifetime, prefix)

        # Consider verifying the content about here.
        return reservation

    async def __aenter__(self):
        """
        Python context manager protocol entrypoint.
        This is what gets called when you enter a with-statement.
        """
        # Clear any earlier deployments
        self.deployments = {}
        self._supporting_reservation = await self._supporting_reservationist.reserve(prefix=self.agent_name)

    async def deploy(self, deployment_dict: Dict[Reservation, Dict[str, Any]], confirmation: bool = False) -> Event:
        """
        Deploy multiple Reservations.

        :param deployment_dict: A dictionary whose keys are Reservation objects
                    previously obtained with reserve() and whose values are each an
                    object to deploy using the key as Reservation.
        :param confirmation: When True, indicates a confirmation Event is desired.
                            When False (the default), no such confirmation is needed.
        :return: Either a confiramtion Event object whose wait() method will confirm
                that the deployment is complete, or None, depending on the value passed
                for confirmation.
        """
        if not deployment_dict:
            return None

        # Do some verification here
        for reservation in deployment_dict.keys():
            key: str = reservation.get_reservation_id()
            self.verify_id(key)

        event: Event = None
        key: Union[str, Event] = None
        if confirmation:
            # Create an async.Event. This will be the key for the dictionary
            event = Event()
            key = event
        else:
            # Use the ID of the first Reservation as the key. This will be unique.
            first_res: Reservation = deployment_dict.keys()[0]
            key = first_res.get_reservation_id()
            # event is already None

        entry: Dict[Union[str, Event], Dict[Reservation, Dict[str, Any]]] = {
            key: deployment_dict
        }
        self.deployments.update(entry)

        return event

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """
        Python context manager protocol exit point.
        This is what gets called when you exit a with-statement.
        This triggers the initiation of the deployment.
        """
        # Initiate the deployments
        await self._supporting_reservationist.deploy_one(self._supporting_reservation, self.deployments)

        # Reset state
        self._supporting_reservation = None
        self.deployments = {}

    @staticmethod
    def verify_id(test_id: str):
        """
        :param test_id:  The id string to test

        Will assert if the given id is not valid for external consumption
        """
        if test_id is None:
            raise ValueError("Reservation id is None")
        if len(test_id) == 0:
            raise ValueError("Reservation id is empty")

        invalid_chars: str = "/: "
        for invalid_char in invalid_chars:
            if invalid_char in test_id:
                # Probably more characters to look for w/rt url validity.
                raise ValueError(f"Reservation id {test_id} cannot contain any of these characters: '{invalid_chars}'")
