
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

from datetime import datetime
from datetime import timedelta
from logging import getLogger
from logging import Logger
from threading import Thread
from time import sleep

from neuro_san.internals.interfaces.startable import Startable
from neuro_san.service.utils.server_context import ServerContext


class WatcherThread(Startable):
    """
    Startable implementation that starts a thread to do its work in run().
    """

    def __init__(self, server_context: ServerContext):
        """
        Constructor

        :param server_context: ServerContext for global-ish state
        """
        self.logger: Logger = getLogger(self.__class__.__name__)
        self.update_thread: Thread = Thread(target=self.run, name=self.__class__.__name__, daemon=True)
        self.keep_running: bool = True
        self.update_period_in_seconds: float = 1.0
        self.server_context: ServerContext = server_context

    def start(self):
        """
        Perform start up.
        """
        self.logger.info("Starting %s with %f seconds period",
                         self.__class__.__name__, self.update_period_in_seconds)
        self.update_thread.start()

    def run(self):
        """
        Main loop
        """
        raise NotImplementedError

    def should_keep_running(self) -> bool:
        """
        :return: True if this instance should keep running. False otherwise.
        """
        return self.keep_running

    def maybe_sleep_at_end_of_iteration(self, start: datetime, verbose: bool = False):
        """
        Maybe sleep at the end of an iteration.

        :param start: The start datetime of the iteration
        :param verbose: If true, log when we took longer than the required interval
        """
        finish: datetime = datetime.now()
        duration: timedelta = finish - start
        duration_seconds: float = duration.total_seconds()
        if duration_seconds > self.update_period_in_seconds:
            if verbose:
                self.logger.warning("%s took %f seconds", self.__class__.__name__, duration_seconds)
        elif duration_seconds < self.update_period_in_seconds:
            # Try to be more efficient w/rt getting to the next iteration
            remaining_seconds: float = self.update_period_in_seconds - duration_seconds
            sleep(remaining_seconds)

    def stop(self):
        """
        Perform steps to stop/shut-down
        By default this does nothing
        """
        self.logger.info("Stopping %s with %f seconds period",
                         self.__class__.__name__, self.update_period_in_seconds)

        self.keep_running = False

        # Wait for the thread to finish only if it was successfully started.
        if self.update_thread.is_alive():
            self.update_thread.join()
