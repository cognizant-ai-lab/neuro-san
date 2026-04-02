
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
from typing import Optional
from typing import Tuple

import logging
import time
import threading

from neuro_san.interfaces.reservation import Reservation
from neuro_san.internals.interfaces.reservations_storage import ReservationsStorage
from neuro_san.internals.interfaces.startable import Startable


class AbstractReservationsStorage(ReservationsStorage, Startable):
    """
    An abstract implementation of ExpiringReservationsStorage interface
    providing a background thread that periodically checks for expired reservations and removes them.
    Specific logic for adding, retrieving, and expiring reservations is left to concrete implementations.
    """

    def __init__(self, storage_name: str = "", check_expirations_interval_seconds: float = 0.0):
        """
        Constructor
        :param storage_name: A string name for this storage, used for logging purposes.
        :param check_expirations_interval_seconds: The number of seconds between checks for expired reservations.
                            If set to 0 or negative, the background thread will not be started.
        """
        super().__init__()
        self._thread: threading.Thread = None
        self._check_interval_seconds: float = check_expirations_interval_seconds
        self._stop_event = threading.Event()
        self._logger = logging.getLogger(self.__class__.__name__)
        self._name: str = storage_name

    def start(self):
        if self._check_interval_seconds > 0:
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()
            self._logger.debug("%s: Expiration cleanup thread started with period %f sec.",
                               self._name, self._check_interval_seconds)
        else:
            self._logger.debug("%s: Expiration cleanup thread not started.", self._name)

    def stop(self, timeout: Optional[float] = None):
        """
        Signal the worker to stop and wait for it with timeout.
        """
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout)
            self._logger.debug("%s: Expiration cleanup thread stopped.", self._name)

    def _run_loop(self):
        while not self._stop_event.is_set():
            # Using "monotonic" time allows us to avoid potential issues with system clock changes
            start = time.monotonic()
            try:
                self.expire_reservations()
            except Exception as exception:  # pylint: disable=broad-except
                self._logger.info("%s: Expiration cleanup failed: %s", self._name, exception)
            elapsed = time.monotonic() - start
            self._logger.debug("%s: Expiration cleanup took %f seconds.", self._name, elapsed)

            # Compute remaining sleep time
            sleep_time = self._check_interval_seconds - elapsed
            if sleep_time > 0:
                # Sleep but wake early if stop is requested,
                # this makes worker thread more responsive to the shutdown requests.
                self._stop_event.wait(timeout=sleep_time)
            # We're behind schedule; skip sleeping (prevents drift accumulation)

    def add_reservations(self, reservations_dict: Dict[Reservation, Any],
                         source: str = None):
        """
        Add a set of reservations for agent networks en-masse

        :param reservations_dict: A mapping of Reservation -> some deployable entity
        :param source: A string describing where the deployment was coming from
        """
        raise NotImplementedError

    def get_one_reservation(self, obj_key: str) -> Tuple[Reservation, Any]:
        """
        Extract a single reservation.

        :param obj_key: unique key for the reservation
        :return: Tuple of (reservation, agent data) if successful
                 and reservation is not expired,
                 (None, None) otherwise
        """
        raise NotImplementedError

    def expire_reservations(self):
        """
        Remove Reservations that are expired
        """
        # Do nothing here.
