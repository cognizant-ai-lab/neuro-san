
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
from typing import AsyncGenerator
from typing import Awaitable
from typing import Dict
from typing import List
from typing import Tuple

from asyncio import Task
from datetime import datetime

from croniter import croniter as CronIter

from leaf_common.asyncio.asyncio_executor import AsyncioExecutor

from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.graph.persistence.periodic_manifest_dict_config_filter import PeriodicManifestDictConfigFilter
from neuro_san.internals.graph.utils.invocation_util import InvocationUtil
from neuro_san.internals.interfaces.invocations import Invocations
from neuro_san.internals.messages.chat_message_type import ChatMessageType
from neuro_san.service.generic.async_agent_service import AsyncAgentService
from neuro_san.service.generic.async_agent_service_provider import AsyncAgentServiceProvider
from neuro_san.service.interfaces.agent_authorizer import AgentAuthorizer
from neuro_san.service.watcher.interfaces.watcher_thread import WatcherThread
from neuro_san.service.utils.server_context import ServerContext


class PeriodicEventInitiator(WatcherThread):
    """
    WatcherThread implementation that looks for periodic manifest specifications
    to poke them on the schedule they want.

    DEF: Need to be sure a storage watcher update can trigger changes in here.
    """

    def __init__(self, server_context: ServerContext):
        """
        Constructor
        """
        super().__init__(server_context)
        self.verbose: bool = False
        self.executor = AsyncioExecutor()
        # Probably need to set up logging in this guy

    def run(self):
        """
        Main loop
        """
        # Start the executor so our async event initiators have someplace to run
        self.executor.start()

        # Get the periodic configs from the ServerContext
        # Will need to update these every so often to pick up changes from the file system watcher.
        periodic_configs: Dict[str, Dict[str, Any]] = self.server_context.get_periodic_configs()

        # Set up the periodic agent interactions in a list
        now: datetime = datetime.now()
        agent_interaction_list: List[Dict[str, Any]] = self.set_up_agent_interactions(now, periodic_configs)

        # Keep track of the next firing times for each index in the agent_interaction_list
        next_firing: Dict[int, datetime] = {}
        closest_firing: datetime = datetime.max

        # Update the next firing times
        next_firing, closest_firing = self.update_next_firing(now, agent_interaction_list, next_firing, closest_firing)

        while self.should_keep_running():

            # Time how long it takes to process the iteration for finer-grained sleep() adjustments at end.
            start: datetime = datetime.now()

            # Figure out which periodic agents need to fire now
            fire_these_now: List[Dict[str, Any]] = self.figure_which_to_fire(start, agent_interaction_list, next_firing)

            # Fire off the periodic agents we need to for this iteration
            self.fire_all_these_now(fire_these_now)

            # Update the next firing dictionary for all the periodic agents
            next_firing, closest_firing = self.update_next_firing(start, agent_interaction_list,
                                                                  next_firing, closest_firing)

            # Optimize sleeping for the next iteration
            self.maybe_sleep_at_end_of_iteration(start, verbose=True)

        self.executor.shutdown()

    def set_up_agent_interactions(
                self,
                start_time: datetime,
                periodic_configs: Dict[str, Dict[str, Any]]
            ) -> List[Dict[str, Any]]:
        """
        Sets up a list of all periodic agent interactions.
        We need this as a list because we cannot use a non-hashable periodic config
        as a key for a dictionary or tuple, but the index into this list is hashable.

        :param start_time: the start time
        :param periodic_configs: the dictionary of agent_network -> periodic configs
        :return: a list of periodic agent interactions
        """
        # What we will return
        agent_interaction_list: List[Dict[str, Any]] = []
        empty_list: List[Dict[str, Any]] = []

        # Loop through the periodic configs, adding a new dictionary for each single agent interaction
        for agent_network, periodic_config in periodic_configs.items():

            # Loop through the interactions
            interactions: List[Dict[str, Any]] = periodic_config.get("interactions", empty_list)
            for interaction in interactions:

                # Only look at enabled interactions
                if not interaction.get("enable", True):
                    continue

                # Get the string representing the cron schedule
                cron_schedule: str = interaction.get("cron_schedule",
                                                     PeriodicManifestDictConfigFilter.DEFAULT_CRON_SCHEDULE)
                second_at_beginning: bool = interaction.get("second_at_beginning", False)

                # Put an iterator in the agent interaction
                iterator = CronIter(cron_schedule, start_time, second_at_beginning=second_at_beginning)

                # Create an agent interaction dictionary for the list
                agent_interaction: Dict[str, Any] = {
                    "agent_network": agent_network,
                    "interaction": interaction,
                    "cron_iter": iterator
                }
                agent_interaction_list.append(agent_interaction)

        self.logger.info("Found %d periodic agent interactions", len(agent_interaction_list))

        return agent_interaction_list

    def update_next_firing(
                self,
                now: datetime,
                agent_interaction_list: List[Dict[str, Any]],
                next_firing: Dict[int, datetime],
                last_closest_firing: datetime
            ) -> Tuple[Dict[int, datetime], datetime]:
        """
        Updates the next firing times

        :param now: The current time
        :param agent_interaction_list: A list of single agent interactions
        :param next_firing: A mapping of agent_interaction_list index -> datetime of next firing
        :param last_closest_firing: The last closest firing
        :return: A tuple of 1) the new next firing mapping  2) The new closest firing datetime
        """
        # What we will return
        new_next_firing: Dict[int, datetime] = {}

        # Set up for figuring out the closest firing
        closest_firing: datetime = last_closest_firing
        if closest_firing < now:
            closest_firing = datetime.max

        # Loop through the agent interactions
        for index, agent_interaction in enumerate(agent_interaction_list):

            # See if we already have a next firing
            next_firing_time: datetime = next_firing.get(index)
            if next_firing_time is not None:

                # If the next firing time is in the future, don't disturb it.
                if next_firing_time > now:
                    new_next_firing[index] = next_firing_time
                    closest_firing = min(closest_firing, next_firing_time)
                    continue

            # Get a new next firing for this agent_interaction
            cron_iter: CronIter = agent_interaction.get("cron_iter")

            # Need to pass the type of what we want back from the iterator
            next_firing_time = cron_iter.get_next(datetime)

            # Slow event processing might require skipping/compressing
            # iterator times that are already in the past. Advance until
            # the next firing is strictly in the future.
            while next_firing_time <= now:
                next_firing_time = cron_iter.get_next(datetime)

            new_next_firing[index] = next_firing_time

            closest_firing = min(closest_firing, next_firing_time)
        if self.verbose and closest_firing != last_closest_firing:
            self.logger.info("Next event firing is at %s", closest_firing)

        return new_next_firing, closest_firing

    def figure_which_to_fire(
                self,
                now: datetime,
                agent_interaction_list: List[Dict[str, Any]],
                next_firing: Dict[int, datetime]
            ) -> List[Dict[str, Any]]:
        """
        Figures out which periodic agent interactions need to fire now.

        :param now: The datetime corresponding to the current moment
        :param agent_interaction_list: A list of single agent interactions
        :param next_firing: A mapping of agent_interaction_list index -> datetime of next firing
        :return: A list of agent interactions to fire
        """
        # What we will return
        fire_these_now: List[Dict[str, Any]] = []

        # Loop through all the next firing times to see which ones are in the past.
        # Those we want to fire now.
        agent_interaction_index: int = None
        next_firing_time: datetime = None
        for agent_interaction_index, next_firing_time in next_firing.items():

            # If the next firing time is in the past, record that we need to initiate the agent
            if next_firing_time < now:
                # Look up the agent interaction given the index
                agent_interaction: Dict[str, Any] = agent_interaction_list[agent_interaction_index]
                fire_these_now.append(agent_interaction)

        return fire_these_now

    def fire_all_these_now(self, fire_these_now: List[Dict[str, Any]]):
        """
        Pokes the given agent networks in the list of agent interactions by their configs.

        :param fire_these_now: A list of agent interaction dictionaries
        """
        if not fire_these_now:
            # Nothing to do
            return

        for agent_interaction in fire_these_now:

            # Get the relevant information from the agent interaction dictionary
            agent_network: str = agent_interaction.get("agent_network")
            interaction: Dict[str, Any] = agent_interaction.get("interaction")

            # Create a task for each agent interaction
            coroutine: Awaitable = self.initiate_event(agent_network, interaction)
            _: Task = self.executor.create_task(coroutine, self.__class__.__name__)
            # Note that we don't really care when the task completes, just as long as it runs.

    async def initiate_event(self, agent_network_name: str, interaction: Dict[str, Any]):
        """
        Pokes the given agent_network_name with the interaction

        :param agent_network_name: The agent_network to poke
        :param interaction: The interaction config to use for the event
        """
        # Get the agent authorizer that is going to tell us whether we are allowed to initiate the event
        agent_authorizer: AgentAuthorizer = self.server_context.get_agent_authorizer()

        # Get any request metadata from the interaction
        empty_dict: Dict[str, Any] = {}
        interaction_metadata: Dict[str, Any] = interaction.get("metadata") or empty_dict
        metadata: Dict[str, Any] = dict(interaction_metadata)
        if metadata.get("user_id") is None:
            metadata["user_id"] = "system"

        authorized: bool = False
        service_provider: AsyncAgentServiceProvider = None
        authorized, service_provider = await agent_authorizer.allow_agent(agent_network_name, metadata)
        if not authorized or not service_provider:
            self.logger.warning("Not authorized to initiate periodic event for agent_network %s", agent_network_name)
            return

        # We are allowed to initiate the event and we have the service_provider with which to do that.

        # Formulate the request to send to the agent
        request_dict: Dict[str, Any] = {
            "user_message": {
                "type": ChatMessageType.HUMAN.name,
                "text": interaction.get("text", ""),
                "sly_data": interaction.get("sly_data", empty_dict),
                "chat_filter": {
                    # Always minimal for event invocation.
                    "chat_filter_type": "MINIMAL"
                }
            }
        }

        # Get the agent network so we can be sure it has the right invocation set
        agent_service: AsyncAgentService = service_provider.get_service()
        agent_network: AgentNetwork = agent_service.get_agent_network()
        invocation: str = InvocationUtil.get_invocation(agent_network)
        if invocation != Invocations.EVENT:
            self.logger.warning("Network %s is not configured for event invocation. Some work may not complete.",
                                agent_network_name)

        # Perform a streaming_chat() on the agent with the formulated request
        results: AsyncGenerator[Dict[str, Any], None] = agent_service.streaming_chat(request_dict, metadata)

        # Wait for the results
        async for result_dict in results:
            # We don't care about the results.
            # We just want to poke the agent and wait for it to be done.
            _: Dict[str, Any] = result_dict
