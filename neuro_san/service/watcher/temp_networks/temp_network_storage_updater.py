
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
from typing import Set

from os import environ

from asyncio import AbstractEventLoop
from asyncio import Event
from asyncio import run_coroutine_threadsafe
from concurrent.futures import ThreadPoolExecutor
from logging import getLogger
from logging import Logger

from janus import Queue

from leaf_common.config.resolver_util import ResolverUtil

from neuro_san.internals.chat.async_collating_queue import AsyncCollatingQueue
from neuro_san.internals.interfaces.reservations_storage import ReservationsStorage
from neuro_san.internals.network_providers.agent_network_storage import AgentNetworkStorage
from neuro_san.internals.reservations.agent_reservation import AgentReservation
from neuro_san.internals.reservations.abstract_agent_reservationist import AbstractAgentReservationist
from neuro_san.service.watcher.interfaces.abstract_storage_updater import AbstractStorageUpdater
from neuro_san.service.interfaces.startable import Startable


class TempNetworkStorageUpdater(AbstractStorageUpdater):
    """
    StorageUpdater implementation for temporary network updates.
    """
    # Size of thread pool for processing reservations queues.
    THREAD_POOL_SIZE: int = 32

    def __init__(self, network_storage_dict: Dict[str, AgentNetworkStorage],
                 watcher_config: Dict[str, Any],
                 queues: Queue[AsyncCollatingQueue]):
        """
        Constructor

        :param network_storage_dict: A dictionary of string (descripting scope) to
                    AgentNetworkStorage instance which keeps all the AgentNetwork instances
                    of a particular grouping.
        :param watcher_config: A config dictionary for StorageUpdaters
        :param queues: A Queue of AsyncCollatingQueues for temp network deployment
        """
        super().__init__(watcher_config.get("temporary_network_update_period_seconds"))
        self.logger: Logger = getLogger(self.__class__.__name__)

        self.reservations_storage: Set[ReservationsStorage] = set()
        temp_storage: ReservationsStorage = network_storage_dict.get("temp")
        if temp_storage is not None:
            # If we don't have temp storage, we don't got nothin'
            self.reservations_storage.add(temp_storage)

            # Potentially create an external storage class
            storage_class_name: str = environ.get("AGENT_EXTERNAL_RESERVATIONS_STORAGE", "")
            external_storage: ReservationsStorage = ResolverUtil.create_instance(
                    storage_class_name,
                    "AGENT_EXTERNAL_RESERVATIONS_STORAGE env var",
                    ReservationsStorage)
            if external_storage is not None:
                self.reservations_storage.add(external_storage)

        self.incoming: Queue[AsyncCollatingQueue] = queues
        self.queue_processing_pool: ThreadPoolExecutor = ThreadPoolExecutor(self.THREAD_POOL_SIZE)
        self.reservationist = AbstractAgentReservationist(self.reservations_storage)

    def start(self):
        """
        Perform start up.
        """
        self.logger.info("Starting TempNetworkStorageUpdater with %d seconds period",
                         self.update_period_in_seconds)

        # Start any Startables
        for storage in self.reservations_storage:
            if isinstance(storage, Startable):
                storage.start()
        # Start the task for checking for new queues to process
        self.queue_processing_pool.submit(self.add_new_queues_to_processing)

    def update_storage(self):
        """
        Perform an update
        """
        # First sync any existing networks from potential external sources
        for storage in self.reservations_storage:
            storage.sync_reservations()

        # First expire any existing networks
        for storage in self.reservations_storage:
            storage.expire_reservations()

        # Get any new queues
        self.add_new_queues_to_pool()

        before = len(self.queue_pool)
        if before == 0:
            return

        # Process all our queues.
        # We take a copy because during processing we might remove a queue from the pool.
        self.logger.info("Updating temp storage from %d queues", before)
        for queue in self.queue_pool.copy():
            self.process_one_queue(queue)

        after = len(self.queue_pool)
        finished = before - after
        if finished > 0:
            self.logger.info("Temp storage from %d queues finished", finished)

    def add_new_queues_to_processing(self):
        """
        Checks our master queue of queues for any new additions
        and adds them to the queue processing pool
        for independent processing of each queue.
        """
        self.logger.info("Waiting for new queues to be added for processing")
        print("Waiting for new queues to be added for processing")
        while True:
            async_collating_queue: AsyncCollatingQueue = self.incoming.sync_q.get()
            # We have a new queue to process.
            # Submit this queue processing  task to our thread pool.
            self.queue_processing_pool.submit(self.process_one_queue, async_collating_queue)

    def process_one_queue(self, async_collating_queue: AsyncCollatingQueue):
        """
        Processes a single AsyncCollatingQueue from the pool

        :param async_collating_queue: The AsyncCollatingQueue to process
        """
        janus_queue: Queue = async_collating_queue.get_queue()

        # See what has come over this particular queue
        while True:
            # Get an item off the queue
            queued_item: Dict[str, Any] = janus_queue.sync_q.get()
            if async_collating_queue.is_final_item(queued_item):
                # We have exhausted this queue.
                # No one needs to worry about it anymore.
                async_collating_queue.close()
                return

            self.process_one_queued_item(queued_item)

    def process_one_queued_item(self, queued_item: Dict[str, Any]):
        """
        Process a single item from one of the queues

        :param queued_item: A dictionary from a queue containing information
                as populated by AgentReservationist.deploy()
        """

        # Get the salient information from the dictionary that was queued.
        source: str = queued_item.get("source")
        deployment_dict: Dict[AgentReservation, Dict[str, Any]] = queued_item.get("deployment_dict")
        max_lifetime_in_seconds: float = queued_item.get("max_lifetime_in_seconds")

        # Do the deployment
        self.reservationist.deploy_together(deployment_dict, source, max_lifetime_in_seconds)

        # Maybe notify the deployer.
        event: Event = queued_item.get("event")
        if event is not None:
            event_loop: AbstractEventLoop = queued_item.get("event_loop")
            run_coroutine_threadsafe(self.reservationist.set_event(event), event_loop)

    def stop(self):
        """
        Perform stopping.
        """
        self.logger.info("Stopping TempNetworkStorageUpdater")

        # Stop any Startables
        for storage in self.reservations_storage:
            if isinstance(storage, Startable):
                storage.stop()
        # Finalize the queue processing pool
        self.queue_processing_pool.shutdown(wait=False, cancel_futures=True)

