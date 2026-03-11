
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
from typing import Any
from typing import Dict
from typing import Union

from asyncio import Event
from asyncio import get_running_loop

from janus import Queue

from neuro_san.interfaces.reservation import Reservation
from neuro_san.interfaces.reservationist import Reservationist
from neuro_san.internals.chat.async_collating_queue import AsyncCollatingQueue
from neuro_san.internals.reservations.agent_reservation import AgentReservation


class ServiceAgentReservationist(Reservationist):
    """
    Reservationist implementation that allows procurement of agent ids
    for a specific amount of time.
    """

    def __init__(self, main_queue: Queue[AsyncCollatingQueue],
                 max_lifetime_in_seconds: float = Reservationist.DEFAULT_LIFETIME):
        """
        Constructor

        :param main_queue: The main Queue of AsyncCollatingQueues to which this instance
                   will add its own AsyncCollatingQueue for deployment when it will be created.
        :param max_lifetime_in_seconds: The maximum lifetime allowed for any Reservation.
        """
        self.max_lifetime_in_seconds: float = max_lifetime_in_seconds
        self.main_queue: Queue[AsyncCollatingQueue] = main_queue
        self.queue: AsyncCollatingQueue = None

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
        if not deployment_dict:
            return None

        for reservation, value in deployment_dict.items():

            to_deploy: Dict[Union[str, Event], Dict[AgentReservation, Dict[str, Any]]] = value
            for key, value in to_deploy.items():

                # Prepare basic information to put on the queue.
                queued_item: Dict[str, Any] = {
                    "source": reservation.get_prefix(),
                    "deployment_dict": value,
                    "max_lifetime_in_seconds": self.max_lifetime_in_seconds
                }

                # The key can be either a string or an asyncio.Event.
                # We don't care so much about the string,
                # but we definitely care about the asyncio.Event.
                # FWIW: The string just means that the caller didn't care
                #   about receiving notice as to when stuff was deployed,
                #   though it does get us the deployment_dict value.
                if isinstance(key, Event):
                    queued_item["event"] = key
                    queued_item["event_loop"] = get_running_loop()

                if self.queue is None:
                    # We haven't created our queue yet, so we need to do that and put it on the main queue.
                    self.queue = AsyncCollatingQueue()
                    self.main_queue.sync_q.put(self.queue)

                await self.queue.put(queued_item, synchronous=False)

        return None

    async def close(self):
        """
        Tell the deployment consumer we are all done.
        """
        # Use synchronous side of the queue because this will not
        # be part of the same event loop the put() in deploy() above is done.
        await self.queue.put_final_item(synchronous=True)
