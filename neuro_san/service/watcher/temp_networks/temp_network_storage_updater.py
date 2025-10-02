
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

from os import environ

from asyncio import AbstractEventLoop
from asyncio import Event
from asyncio import run_coroutine_threadsafe
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
from neuro_san.service.watcher.interfaces.startable import Startable


class TempNetworkStorageUpdater(AbstractStorageUpdater):
    """
    StorageUpdater implementation for temporary network updates.
    """

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
            storage_class_name: str = environ.get("AGENT_EXTERNAL_RESERVATIONS_STORAGE")
            external_storage: ReservationsStorage = ResolverUtil.create_instance(
                    storage_class_name,
                    "AGENT_EXTERNAL_RESERVATIONS_STORAGE env var",
                    ReservationsStorage)
            if external_storage is not None:
                self.reservations_storage.add(external_storage)

            # The ultimate target for sync is the temp storage
            for storage in self.reservations_storage:
                storage.set_sync_target(temp_storage)

        self.incoming: Queue[AsyncCollatingQueue] = queues
        self.queue_pool: Set[AsyncCollatingQueue] = set()
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

    def add_new_queues_to_pool(self):
        """
        Checks our master queue of queues for any new additions
        and adds them to the queue pool we need to pay attention to.
        """
        while self.incoming.sync_q.qsize() > 0:
            async_collating_queue: AsyncCollatingQueue = self.incoming.sync_q.get()
            self.queue_pool.add(async_collating_queue)

    def process_one_queue(self, async_collating_queue: AsyncCollatingQueue):
        """
        Processes a single AsyncCollatingQueue from the pool

        :param async_collating_queue: The AsyncCollatingQueue to process
        """
        janus_queue: Queue = async_collating_queue.get_queue()

        # See what has come over this particular queue
        while janus_queue.sync_q.qsize() > 0:

            # Get an item off the queue
            queued_item: Dict[str, Any] = janus_queue.sync_q.get()
            if async_collating_queue.is_final_item(queued_item):
                # We have exhausted this queue.
                # No one needs to worry about it any more.
                self.queue_pool.remove(async_collating_queue)
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
