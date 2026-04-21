
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

from neuro_san.internals.graph.persistence.periodic_manifest_dict_config_filter import PeriodicManifestDictConfigFilter
from neuro_san.internals.messages.chat_message_type import ChatMessageType
from neuro_san.service.generic.async_agent_service import AsyncAgentService
from neuro_san.service.generic.async_agent_service_provider import AsyncAgentServiceProvider
from neuro_san.service.interfaces.agent_authorizer import AgentAuthorizer
from neuro_san.service.watcher.interfaces.watcher_thread import WatcherThread


class PeriodicEventInitiator(WatcherThread):
    """
    WatcherThread implementation that looks for periodic manifest specifications
    to poke them on the schedule they want.

    DEF: Need to be sure a storage watcher update can trigger changes in here.
    """

    def __init__(self, server_context: Any):
        """
        Constructor
        """
        super().__init__(server_context)
        self.executor = AsyncioExecutor()
        # Probably need to set up logging in this guy

    def run(self):
        """
        Main loop
        """
        periodic_configs: Dict[str, Dict[str, Any]] = self.server_context.get_periodic_configs()

        now: datetime = datetime.now()
        iterators: Dict[str, Dict[Dict[str, Any], CronIter]] = self.set_up_iterators(now, periodic_configs)

        self.executor.start()

        next_firing: Dict[Tuple[str, Dict[str, Any]], datetime] = {}

        while self.should_keep_running():

            # Time how long it takes to process the iteration for finer-grained sleep() adjustments at end.
            start: datetime = datetime.now()

            # Update the next firing dictionary for all the periodic agents
            next_firing = self.update_next_firing(start, iterators, next_firing)

            fire_these_now: Dict[str, Dict[str, Any]] = {}

            # Loop through all the next firing times to see which ones are in the past.
            # Those we want to fire now.
            tuple_key: Tuple[str, Dict[str, Any]] = None
            next_firing_time: datetime = None
            for tuple_key, next_firing_time in next_firing.items():

                # If the next firing time is in the past, record that we need to initiate the agent
                if next_firing_time < start:
                    agent_network: str = tuple_key[0]
                    periodic_config: Dict[str, Any] = tuple_key[1]
                    fire_these_now[agent_network] = periodic_config

            # Fire off the periodic agents we need to for this iteration
            self.fire_all_these_now(fire_these_now)

            # Optimize sleeping for the next iteration
            self.maybe_sleep_at_end_of_iteration(start, verbose=True)

        self.executor.shutdown()

    def set_up_iterators(
                self,
                start_time: datetime,
                periodic_configs: Dict[str, Dict[str, Any]]
            ) -> Dict[str, Dict[Dict[str, Any], CronIter]]:
        """
        Sets up the Cron iterators

        :param start_time: the start time basis for the CronIters
        :return: a mapping of agent_network to another mapping of interaction dictionary -> CronIter
        """
        # What we will return
        iterators: Dict[str, Dict[Dict[str, Any], CronIter]] = {}

        # Loop through the periodic configs
        for agent_network, config in periodic_configs.items():

            # Find all the interactions in the config
            empty_list: List[Dict[str, Any]] = []
            interactions: List[Dict[str, Any]] = config.get("interactions", empty_list)
            interaction_to_iterator: Dict[Dict[str, Any], CronIter] = {}
            for interaction in interactions:

                # Only look at enabled interactions
                if interaction.get("enable", True):

                    # Get the string representing the cron schedule
                    cron_schedule: str = interaction.get("cron_schedule",
                                                         PeriodicManifestDictConfigFilter.DEFAULT_CRON_SCHEDULE)
                    # Put an iterator in the inner mapping
                    iterator = CronIter(cron_schedule, start_time)
                    interaction_to_iterator[interaction] = iterator

            # Put the inner mapping in the outer mapping
            iterators[agent_network] = interaction_to_iterator

        return iterators

    def update_next_firing(
                self,
                now: datetime,
                iterators: Dict[str, Dict[Dict[str, Any], CronIter]],
                next_firing: Dict[Tuple[str, Dict[str, Any]], datetime]
            ) -> Dict[Tuple[str, Dict[str, Any]], datetime]:
        """
        Updates the next firing times

        :param now: The current time
        :param iterators: A mapping of agent_network to another mapping of interaction dictionary -> CronIter
        :param next_firing: A mapping of agent_network/interaction dictionary to datetime of next firing
        :return: A new next firing mapping
        """
        # What we will return
        new_next_firing: Dict[Tuple[str, Dict[str, Any]], datetime] = {}

        agent_network: str = None
        interaction_to_iterator: Dict[Dict[str, Any], CronIter] = None

        # Loop through the outer mapping whose key is the agent network name
        for agent_network, interaction_to_iterator in iterators.items():

            interaction: Dict[str, Any] = None
            cron_iter: CronIter = None

            # Loop through the inner mapping of interaction dict to CronIter
            for interaction, cron_iter in interaction_to_iterator.items():

                # See if we already have a next firing
                tuple_key: Tuple[str, Dict[str, Any]] = (agent_network, interaction)
                next_firing_time: datetime = next_firing.get(tuple_key)
                if next_firing_time is not None:

                    # If the next firing time is in the future, don't disturb it.
                    if next_firing_time > now:
                        new_next_firing[tuple_key] = next_firing_time
                        continue

                # Get a new next firing for this agent_network
                next_firing_time = cron_iter.get_next()
                new_next_firing[tuple_key] = next_firing_time

                # Slow event processing might require skipping/compressing
                # some iterator times that are in the past, but not there yet.

        return new_next_firing

    def fire_all_these_now(self, fire_these_now: Dict[str, Dict[str, Any]]):
        """
        Pokes the given agent_network keys with input described by
        the periodic_config values.

        :param agent_network: The agent_network to poke
        :param periodic_config: The periodic config
        """
        if not fire_these_now:
            return

        for agent_network, periodic_config in fire_these_now.items():
            coroutine: Awaitable = self.initiate_event(agent_network, periodic_config)
            _: Task = self.executor.create_task(coroutine, self.__class__.__name__)
            # Note that we don't really care when the task completes, just as long as it runs.

    async def initiate_event(self, agent_network: str, periodic_config: Dict[str, Any]):
        """
        Pokes the given agent_network with the periodic_config

        :param agent_network: The agent_network to poke
        :param periodic_config: The periodic config to use for the event
        """
        agent_authorizer: AgentAuthorizer = self.server_context.get_agent_authorizer()

        empty_dict: Dict[str, Any] = {}
        metadata: Dict[str, Any] = periodic_config.get("metadata", empty_dict)

        authorized: bool = False
        service_provider: AsyncAgentServiceProvider = None
        authorized, service_provider = await agent_authorizer.allow_agent(agent_network, metadata)
        if not authorized:
            self.logger.warning("Not authorized to initiate periodic event for agent_network %s", agent_network)
            return

        agent_service: AsyncAgentService = service_provider.get_service()

        request_dict: Dict[str, Any] = {
            "user_message": {
                "type": ChatMessageType.HUMAN.name,
                "text": periodic_config.get("text", ""),
                "sly_data": periodic_config.get("sly_data", empty_dict),
                "chat_filter": {
                    "chat_filter_type": "MINIMAL"   # Always minimal for event invocation.
                }
            }
        }

        results: AsyncGenerator[Dict[str, Any], None] = await agent_service.streaming_chat(request_dict, metadata)
        async for result_dict in results:
            # We don't care about the results.
            # We just want to poke the agent and wait for it to be done.
            _: Dict[str, Any] = result_dict
