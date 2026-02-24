
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
from neuro_san.internals.interfaces.expiring_reservations_storage import ExpiringReservationsStorage
from neuro_san.internals.interfaces.startable import Startable


class AbstractExpiringReservationsStorage(ExpiringReservationsStorage, Startable):
    """
    An abstract implementation of ExpiringReservationsStorage interface
    providing a background thread that periodically checks for expired reservations and removes them.
    Specific logic for adding, retrieving, and expiring reservations is left to concrete implementations.
    """

    def __init__(self, check_expirations_interval_seconds: float = 60.0):
        """
        Constructor
        :param check_expirations_interval_seconds: The number of seconds between checks for expired reservations.
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
            # Using "monotonic" time allows us to avoid potential issues with system clock changes
            start = time.monotonic()
            try:
                self.expire_reservations()
            except Exception as exception:  # pylint: disable=broad-except
                self._logger.info("Expiration cleanup failed: %s", exception)
            elapsed = time.monotonic() - start
            self._logger.debug("Expiration cleanup took %f seconds.", elapsed)

            # Compute remaining sleep time
            sleep_time = self._check_interval_seconds - elapsed
            if sleep_time > 0:
                # Sleep but wake early if stop is requested,
                # this makes worker thread more responsive to shutdown requests.
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

    def set_base_storage(self, base_storage: ExpiringReservationsStorage):
        """
        Set a "base" storage to use as a source of truth for reservations.
        This is optional, but if set, will be used as the source of truth for reservations
        and the implementing class will act as a cache in front of it.
        :param base_storage: An ExpiringReservationsStorage instance to use as a source of truth
        """
        raise NotImplementedError

    def expire_reservations(self):
        """
        Remove Reservations that are expired
        """
        # Do nothing here.
