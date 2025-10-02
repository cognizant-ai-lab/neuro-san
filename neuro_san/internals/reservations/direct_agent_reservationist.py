
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

from asyncio import AbstractEventLoop
from asyncio import Event
from asyncio import get_running_loop
from asyncio import run_coroutine_threadsafe

from neuro_san.interfaces.reservation import Reservation
from neuro_san.internals.reservations.abstract_agent_reservationist import AbstractAgentReservationist
from neuro_san.internals.reservations.agent_reservation import AgentReservation


class DirectAgentReservationist(AbstractAgentReservationist):
    """
    Reservationist implementation that allows procurement of agent ids
    for a specific amount of time for direct sessions only.
    """

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
        # Expire any reservations that need to be.
        for storage in self.reservations_storage:
            storage.expire_reservations()

        if not deployment_dict:
            return None

        for reservation, value in deployment_dict.items():

            to_deploy: Dict[Union[str, Event], Dict[AgentReservation, Dict[str, Any]]] = value
            for key, value in to_deploy.items():

                # Prepare basic information
                source = reservation.get_prefix()
                deployment_dict = value
                max_lifetime_in_seconds = self.max_lifetime_in_seconds

                # Do the deployment
                self.deploy_together(deployment_dict, source, max_lifetime_in_seconds)

                # The key can be either a string or an asyncio.Event.
                # We don't care so much about the string,
                # but we definitely care about the asyncio.Event.
                # FWIW: The string just means that the caller didn't care
                #   about receiving notice as to when stuff was deployed,
                #   though it does get us the deployment_dict value.
                if isinstance(key, Event):
                    event = key
                    event_loop: AbstractEventLoop = get_running_loop()
                    run_coroutine_threadsafe(self.set_event(event), event_loop)

        return None
