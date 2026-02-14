
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
from typing import Optional

import logging
import time
import threading

from neuro_san.internals.interfaces.expiring_reservations_storage import ExpiringReservationsStorage
from neuro_san.service.interfaces.startable import Startable


class AbstractExpiringReservationsStorage(ExpiringReservationsStorage, Startable):
    """
    An AgentNetworkStorage instance where AgentNetworks are allowed to expire.
    This implementation also allows for an optional "source" storage to be set,
    which will be used as a "base" source of truth.
    """

    def __init__(self, check_expirations_interval_seconds: float = 60.0):
        """
        Constructor
        """
        super().__init__()
        self._thread: threading.Thread = None
        self._check_interval_seconds: float = check_expirations_interval_seconds
        self._stop_event = threading.Event()
        self._logger = logging.getLogger(self.__class__.__name__)

    def stop(self, timeout: Optional[float] = None):
        """
        Signal the worker to stop and wait for it with timeout.
        """
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout)
            self._logger.debug("Expiration cleanup thread stopped.")

    def start(self):
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        self._logger.debug("Expiration cleanup thread started.")

    def _run_loop(self):
        while not self._stop_event.is_set():
            start = time.monotonic()
            try:
                self.expire_reservations()
            except Exception as exception:  # pylint: disable=broad-except
                self._logger.info("Expiration cleanup failed: %s", exception)
            elapsed = time.monotonic() - start
            print(f"Expiration cleanup took {elapsed} seconds.")

            # Compute remaining sleep time
            sleep_time = self._check_interval_seconds - elapsed
            if sleep_time > 0:
                # Sleep but wake early if stop is requested
                self._stop_event.wait(timeout=sleep_time)
            # We're behind schedule; skip sleeping (prevents drift accumulation)

    def expire_reservations(self):
        """
        Remove Reservations that are expired
        """
        # Do nothing here.
