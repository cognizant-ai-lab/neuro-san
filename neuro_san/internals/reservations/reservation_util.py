
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
from typing import Tuple

from asyncio import Event

from neuro_san.interfaces.reservation import Reservation
from neuro_san.interfaces.reservationist import Reservationist


class ReservationUtil:
    """
    A static utility class intended to be used from an asynchronous CodedTool that makes
    Agent (network) Reservations easier.
    """

    @staticmethod
    async def wait_for_one(args: Dict[str, Any], agent_spec: Dict[str, Any], lifetime_in_seconds: float,
                           prefix: str = "") \
            -> Tuple[Reservation, str]:
        """
        Waits for a single agent to be deployed as a temporary agent network.

        :param args:  The args for the CodedTool
        :param agent_spec: The dictionary containing the agent network specification
        :param lifetime_in_seconds: How long the temporary agent network should live, in seconds
        :param prefix: An optional prefix to attach to the generated reservation id.
        :return: A tuple containing the Reservation representing the agent network that was deployed
                and a string representing an error message pertaining to the Reservation.  One
                of the elements of the Tuple will be None.
        """
        reservation: Reservation = None
        error: str = None

        reservationist: Reservationist = args.get("reservationist")
        if reservationist is None:
            error = """
Reservationist is None.  Try this for your server:
    export AGENT_TEMPORARY_NETWORK_UPDATE_PERIOD_SECONDS=5
"""
            return (reservation, error)

        # Creating the Reservations can be done outside the Reservationist with-statement
        reservation: Reservation = await reservationist.reserve(lifetime_in_seconds=lifetime_in_seconds,
                                                                prefix=prefix)
        deployments: Dict[Reservation, Dict[str, Any]] = {
            reservation: agent_spec
        }

        # Deploy the reservations with confirmation event
        # If you don't really need to wait until the new agent(s) has been deployed
        # then set confirmation=False, and don't bother about waiting for the Event.
        deployed_event: Event = None
        async with reservationist:
            deployed_event = await reservationist.deploy(deployments, confirmation=True)

        if deployed_event is not None:
            await deployed_event.wait()

        return (reservation, error)
