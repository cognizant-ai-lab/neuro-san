
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
from typing import List
from typing import Tuple

from asyncio import Event

from neuro_san.interfaces.reservation import Reservation
from neuro_san.interfaces.reservationist import Reservationist


class ReservationUtil:
    """
    A static utility class intended to be used from an asynchronous CodedTool that makes
    Agent (network) Reservations easier.
    """

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    @staticmethod
    async def wait_for_one(args: Dict[str, Any], agent_spec: Dict[str, Any], lifetime_in_seconds: float,
                           prefix: str = "", external_networks: List[str] = None, mcp_servers: List[str] = None) \
            -> Tuple[Reservation, str]:
        """
        Waits for a single agent to be deployed as a temporary agent network.

        :param args:  The args for the CodedTool
        :param agent_spec: The dictionary containing the agent network specification
        :param lifetime_in_seconds: How long the temporary agent network should live, in seconds
        :param prefix: An optional prefix to attach to the generated reservation id.
        :param external_networks: An optional list of valid external networks that are to be validated against
        :param mcp_servers: An optional list of valid MCP servers that are to be validated against
        :return: A tuple containing the Reservation representing the agent network that was deployed
                and a string representing an error message pertaining to the Reservation.  One
                of the elements of the Tuple will be None.
        """
        reservation: Reservation = None
        error: str = None

        reservationist: Reservationist = args.get("reservationist")
        if reservationist is None:
            error = """
Reservationist is None.  Make sure that temporary networks reservations
 are allowed in agent network definition by specifying:
"allow": { "reservations": True } or
 add a NetworkCopyMiddleware entry with allow.reservations = true.
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
        try:
            async with reservationist.validate_with(external_networks=external_networks, mcp_servers=mcp_servers):
                deployed_event = await reservationist.deploy(deployments, confirmation=True)

        except ValueError as exception:
            # Report exceptions from below as errors here.
            error = f"{exception}"

        if deployed_event is not None:
            await deployed_event.wait()

        return (reservation, error)
