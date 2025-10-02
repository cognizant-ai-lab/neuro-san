
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

from asyncio import Event

from neuro_san.interfaces.reservation import Reservation


class Reservationist:
    """
    An interface that allows procurement of ids for a specific amount of time.

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

    DEFAULT_LIFETIME: float = 24 * 60 * 60  # one day in seconds

    async def reserve(self, lifetime_in_seconds: float = DEFAULT_LIFETIME,
                      prefix: str = "") -> Reservation:
        """
        Creates a reservation for a specific time period.

        :param lifetime_in_seconds: The lifetime of the reservation
        :param prefix: A string prefix to prepend to the id so as to provide external context.
        :return: A new Reservation object corresponding to the request.
        """
        raise NotImplementedError

    async def __aenter__(self):
        """
        Python context manager protocol entrypoint.
        This is what gets called when you enter a with-statement.
        """

    async def deploy(self, deployment_dict: Dict[Reservation, Any], confirmation: bool = False) -> Event:
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
        raise NotImplementedError

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """
        Python context manager protocol exit point.
        This is what gets called when you exit a with-statement.
        This triggers the initiation of the deployment.
        """

    async def deploy_one(self, reservation: Reservation, deployment: Any, confirmation: bool = False) -> Event:
        """
        Convenience method to deploy a single Reservation.

        :param reservation: A Reservation object previously obtained with reserve()
        :param deployment: The object to deploy
        :param confirmation: When True, indicates a confirmation Event is desired.
                            When False (the default), no such confirmation is needed.
        :return: Either a confiramtion Event object whose wait() method will confirm
                that the deployment is complete, or None, depending on the value passed
                for confirmation.
        """
        deployment_dict: Dict[Reservation, Any] = {reservation: deployment}
        event: Event = await self.deploy(deployment_dict, confirmation=confirmation)
        return event

    async def close(self):
        """
        Indicates we are done using the Reservationist instance.
        By default this does nothing.
        """
