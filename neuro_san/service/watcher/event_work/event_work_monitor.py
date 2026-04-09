
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

from typing import Set

from logging import getLogger
from logging import Logger
from queue import Empty
from threading import Event
from threading import Thread
from time import sleep

from janus import Queue
from janus import SyncQueueShutDown


from neuro_san.internals.interfaces.invocation_context import InvocationContext
from neuro_san.internals.interfaces.startable import Startable
from neuro_san.internals.chat.async_collating_queue import AsyncCollatingQueue
from neuro_san.service.utils.server_context import ServerContext


class EventWorkMonitor(Startable):
    """
    Startable implementation that looks for work from event invocations
    that is finishing up so as to shut down their resources correctly.
    """

    def __init__(self, server_context: ServerContext):
        """
        Constructor

        :param server_context: ServerContext for global-ish state
        """
        self.event_work_queue: AsyncCollatingQueue = server_context.get_event_work_queue()
        self.logger: Logger = getLogger(self.__class__.__name__)
        self.update_thread: Thread = Thread(target=self._run, name="EventWorkMonitor", daemon=True)
        self.keep_running: bool = True
        self.update_period_in_seconds: float = 0.5
        self.invocation_context_pool: Set[InvocationContext] = set()

    def start(self):
        """
        Perform start up.
        """
        self.logger.info("Starting EventWorkMonitor with %f seconds period",
                         self.update_period_in_seconds)
        self.update_thread.start()

    def _run(self):
        """
        Main loop
        """
        janus_queue: Queue = self.event_work_queue.get_queue()

        while self.keep_running:

            queued_item: InvocationContext = None
            try:
                queued_item = janus_queue.sync_q.get_nowait()

            except Empty:
                if janus_queue.sync_q.closed:
                    self.logger.info("EventWorkMonitor shutting down")
                    return

            except SyncQueueShutDown:
                self.logger.info("SHUTDOWN signal for EventWorkMonitor queue")
                return

            if self.event_work_queue.is_final_item(queued_item):
                self.event_work_queue.close()
                self.logger.info("EventWorkMonitor shutting down from final item")
                return

            if queued_item is not None:
                self.invocation_context_pool.add(queued_item)

            self.process_pool()

            sleep(self.update_period_in_seconds)

    def process_pool(self):
        """
        Process the pool of InvocationContexts we need to monitor
        """
        done_invocations: Set[InvocationContext] = set()

        # See which ones are done
        for invocation_context in self.invocation_context_pool:
            done_event: Event = invocation_context.get_work_done_event()
            if done_event.is_set():
                done_invocations.add(invocation_context)

        # Process the done ones
        for invocation_context in done_invocations:

            # Clean up the resources of the invocation_context
            invocation_context.done_with_work("EventWorkMonitor")

            # No need to check on this guy any more
            self.invocation_context_pool.remove(invocation_context)

    def stop(self):
        """
        Perform steps to stop/shut-down
        By default this does nothing
        """
        self.logger.info("Stopping EventWorkMonitor with %f seconds period",
                         self.update_period_in_seconds)

        self.keep_running = False

        # Wait for the thread to finish
        self.update_thread.join()
