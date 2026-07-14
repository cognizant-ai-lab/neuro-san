
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
"""
Local-filesystem implementation of the reservations storage interface.

Mirrors the semantics of S3ReservationsStorage / S3ReservationsWriter /
S3ReservationsReader / S3ReservationsExpiration, but persists each
reservation as a JSON file under a configurable local directory. Intended
for single-node deployments, tests, and local development where standing
up S3 is overkill.

On-disk layout:
    <base_path>/<reservation_id>.json

On-disk JSON schema per reservation (same as the S3 variant):
    {
        "name": ...,
        "llm_config": ...,
        "tools": ...,
        ...                          # any other agent_spec top-level fields
        "metadata": {
            ...                                          # user-authored metadata (merged in)
            "reservation": {
                "id": <str>,
                "lifetime_in_seconds": <float>,
                "expiration_time_in_seconds": <float>,
            },
            "stored_at": <float>,                        # time.time() at write
        }
    }
"""

import asyncio
import json
import logging
import os
import time
from typing import Any
from typing import Dict
from typing import Iterable
from typing import Tuple

from neuro_san.interfaces.reservation import Reservation
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.network_providers.abstract_reservations_storage import AbstractReservationsStorage
from neuro_san.internals.reservations.reservation_dictionary_converter import ReservationDictionaryConverter


class LocalReservationsStorage(AbstractReservationsStorage):
    """
    Local-filesystem implementation of ReservationsStorage.

    Each reservation is written as a JSON file named
    <base_path>/<reservation_id>.json. Writes are atomic (write to a
    temp file then rename) so partial files never appear on read.

    Constructor accepts a base_path pointing at the directory to store
    reservations. The directory is created on start() if it doesn't exist.

    All three concrete operations of the storage interface are implemented
    in this single module -- add_reservations, get_one_reservation,
    expire_reservations -- since the file-based paths are short enough
    that splitting them buys nothing.
    """

    # Suffix used for the on-disk files. Kept as a constant so expiration/read
    # paths agree on which files belong to us and which are foreign.
    RESERVATION_FILE_SUFFIX: str = ".json"

    # Bounded concurrency for concurrent writes inside a single add_reservations call.
    # Local file I/O is fast, but unbounded gather() with a huge batch still burns
    # thread-pool workers unnecessarily. 16 is a reasonable default; local I/O
    # saturates at ~10-20 concurrent writes on most hardware.
    MAX_CONCURRENT_WRITES: int = 16

    def __init__(self, base_path: str = "", check_expirations_interval_seconds: float = 0.0):
        """
        :param base_path: Local directory where reservation JSON files will be stored.
                          Created on start() if it doesn't exist.
        :param check_expirations_interval_seconds: How often to check for expired
                          reservations (via the AbstractReservationsStorage's
                          background thread). 0 or negative disables the periodic
                          check; call expire_reservations() manually when needed.
        """
        super().__init__(storage_name="local_storage",
                         check_expirations_interval_seconds=check_expirations_interval_seconds)
        self.logger: logging.Logger = logging.getLogger(self.__class__.__name__)

        env_path: str = os.getenv("AGENT_RESERVATIONS_LOCAL_PATH", "")
        self.base_path = base_path.strip() if isinstance(base_path, str) else ""

        if not self.base_path:
            self.base_path = env_path.strip()

        if not self.base_path:
            raise ValueError(
                "Local path for reservations must be non-empty string provided via base_path parameter or "
                "AGENT_RESERVATIONS_LOCAL_PATH environment variable"
            )

        self.base_path: str = os.path.abspath(self.base_path)
        self.converter: ReservationDictionaryConverter = ReservationDictionaryConverter()

    def start(self):
        """
        Ensure the storage directory exists and start the periodic expiration
        thread (if configured). Safe to call multiple times.
        """
        os.makedirs(self.base_path, exist_ok=True)
        self.logger.info("%s: using local reservations directory %s",
                         self._name, self.base_path)
        super().start()

    # ---------------------------------------------------------------------
    # Write path
    # ---------------------------------------------------------------------

    async def add_reservations(self, reservations_dict: Dict[Reservation, Any],
                               source: str = None):
        """
        Persist a batch of reservations. Writes are performed concurrently
        (bounded by a semaphore) via asyncio.to_thread to keep the event
        loop responsive while file I/O runs on the thread pool.

        :param reservations_dict: Mapping of Reservation -> deployable agent spec.
                                  The caller's agent_spec is NOT mutated;
                                  a shallow copy is written.
        :param source: Optional string identifying the caller (used for logging).
        """
        if not reservations_dict:
            return
        if source is None:
            source = self._name

        self.logger.info("%s: writing %d reservations to %s",
                         source, len(reservations_dict), self.base_path)

        semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_WRITES)

        async def bounded_write(reservation: Reservation, agent_spec: Dict[str, Any]) -> None:
            async with semaphore:
                await asyncio.to_thread(self._write_one_reservation_sync,
                                        reservation, agent_spec, source)

        await asyncio.gather(*(
            bounded_write(reservation, agent_spec)
            for reservation, agent_spec in reservations_dict.items()
        ))

    def _write_one_reservation_sync(self, reservation: Reservation,
                                    agent_spec: Dict[str, Any], source: str) -> None:
        """
        Synchronous per-reservation writer. Builds the JSON body, writes
        to a temp file in the same directory, then atomically renames it
        onto the final path. Safe against concurrent writers and readers.
        """
        reservation_id: str = reservation.get_reservation_id()
        final_path: str = self._path_for(reservation_id)

        # Shallow-copy so we do not mutate the caller's agent_spec.
        spec_to_write: Dict[str, Any] = dict(agent_spec)
        existing_metadata: Any = spec_to_write.get("metadata") or {}
        if not isinstance(existing_metadata, dict):
            self.logger.warning("%s: reservation %s has non-dict metadata; overwriting it", source, reservation_id)
            existing_metadata = {}
        spec_to_write["metadata"] = {
            **existing_metadata,
            "reservation": self.converter.to_dict(reservation),
            "stored_at": time.time(),
        }

        # Compact JSON: we don't need pretty printing on disk. Callers that
        # want a human-readable view can re-dump on read.
        body: str = json.dumps(spec_to_write, separators=(",", ":"))

        # Write to a temp file in the same directory so os.replace() is atomic.
        # A distinct temp filename per attempt avoids collisions on retries or
        # concurrent overwrites.
        tmp_path: str = f"{final_path}.{os.getpid()}.{time.time_ns()}.tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as fh:
                fh.write(body)
            os.replace(tmp_path, final_path)
        except OSError as exc:
            # Best-effort cleanup of the temp file if the rename failed.
            try:
                os.remove(tmp_path)
            except OSError:
                pass
            self.logger.error("%s: failed to write reservation %s: %s",
                              source, reservation_id, exc)
            raise

        self.logger.debug("%s: wrote reservation %s to %s",
                          source, reservation_id, final_path)

    # ---------------------------------------------------------------------
    # Read path
    # ---------------------------------------------------------------------

    # pylint: disable=too-many-return-statements
    def get_one_reservation(self, obj_key: str) -> Tuple[Reservation, AgentNetwork]:
        """
        Retrieve a single reservation by its reservation_id.

        :param obj_key: The reservation_id to look up.
        :return: (reservation, agent_network) on success, (None, None) if the
                 file is missing, malformed, or the reservation has expired.
        """
        reservation_id: str = obj_key
        reservation: Reservation = None
        agent_network: AgentNetwork = None

        try:
            path: str = self._path_for(reservation_id)
            with open(path, "r", encoding="utf-8") as fh:
                agent_spec: Dict[str, Any] = json.load(fh)
        except ValueError as exc:
            self.logger.debug("%s: invalid reservation_id %r: %s",
                              self._name, reservation_id, exc)
            return None, None
        except FileNotFoundError:
            self.logger.debug("%s: reservation %s not found (path=%s)",
                              self._name, reservation_id, path)
            return None, None
        except OSError as exc:
            self.logger.error("%s: I/O error reading reservation %s: %s",
                              self._name, reservation_id, exc)
            return None, None
        except json.JSONDecodeError as exc:
            self.logger.error("%s: JSON decode error reading reservation %s: %s",
                              self._name, reservation_id, exc)
            return None, None

        try:
            metadata: Dict[str, Any] = agent_spec.get("metadata") or {}
            reservation_dict: Dict[str, Any] = metadata.get("reservation")
            if reservation_dict is None:
                self.logger.error("%s: reservation %s file has no metadata.reservation block",
                                  self._name, reservation_id)
                return None, None
            reservation = self.converter.from_dict(reservation_dict)
            if time.time() > reservation.get_expiration_time_in_seconds():
                self.logger.debug("%s: reservation %s is expired", self._name, reservation_id)
                return None, None
            agent_network = AgentNetwork(agent_spec, reservation.get_reservation_id())
        except Exception as exc:  # pylint: disable=broad-exception-caught
            # Any shape error during reconstruction -- treat as "not present"
            # rather than crashing the caller. Matches the S3 reader's behavior.
            self.logger.error("%s: failed to reconstruct reservation %s: %s",
                              self._name, reservation_id, exc)
            return None, None

        return reservation, agent_network

    # ---------------------------------------------------------------------
    # Expiration path
    # ---------------------------------------------------------------------

    def expire_reservations(self):
        """
        Walk every reservation file under base_path, delete the ones whose
        expiration_time_in_seconds is in the past. Errors on individual
        files are logged but do not abort the sweep.
        """
        self.logger.debug("%s: starting local expiration sweep in %s",
                          self._name, self.base_path)
        current_time: float = time.time()
        expired_count: int = 0

        for path in self._iter_reservation_files():
            if self._expire_one_file(path, current_time):
                expired_count += 1

        if expired_count > 0:
            self.logger.info("%s: expiration sweep removed %d expired reservations",
                             self._name, expired_count)
        else:
            self.logger.debug("%s: expiration sweep removed no reservations", self._name)

    def _iter_reservation_files(self) -> Iterable[str]:
        """
        Yields the full paths of every *.json file directly under base_path.
        Missing directory is treated as "empty."
        """
        try:
            with os.scandir(self.base_path) as scanner:
                for entry in scanner:
                    if entry.is_file() and entry.name.endswith(self.RESERVATION_FILE_SUFFIX):
                        yield entry.path
        except FileNotFoundError:
            # Directory not yet created -- nothing to expire.
            pass

    def _expire_one_file(self, path: str, current_time: float) -> bool:
        """
        Read one reservation file, check its expiration timestamp, and
        delete the file if expired. Returns True iff a file was deleted.

        Any I/O or JSON error during the read is treated as "not our problem
        to expire" (log + move on) rather than an aborting error. That matches
        the S3 expiration path's tolerance for concurrent writers.
        """
        # pylint: disable=too-many-return-statements
        try:
            with open(path, "r", encoding="utf-8") as fh:
                agent_spec: Dict[str, Any] = json.load(fh)
        except FileNotFoundError:
            # Race with another expiration/writer -- fine.
            return False
        except OSError as exc:
            self.logger.error("%s: I/O error reading %s during expiration: %s",
                              self._name, path, exc)
            return False
        except json.JSONDecodeError as exc:
            self.logger.error("%s: JSON decode error on %s during expiration: %s",
                              self._name, path, exc)
            return False

        metadata: Dict[str, Any] = agent_spec.get("metadata") or {}
        reservation_data = metadata.get("reservation")
        if not isinstance(reservation_data, dict):
            self.logger.debug("%s: skipping non-reservation json file during expiration: %s",
                              self._name, path)
            return False
        try:
            expiration_time: float = float(reservation_data["expiration_time_in_seconds"])
        except (KeyError, TypeError, ValueError) as exc:
            self.logger.error("%s: invalid expiration_time_in_seconds in %s: %s",
                              self._name, path, exc)
            return False
        if current_time <= expiration_time:
            return False

        try:
            os.remove(path)
        except FileNotFoundError:
            # Already gone -- another sweeper won the race. Count it as expired.
            return True
        except OSError as exc:
            self.logger.error("%s: failed to delete expired reservation %s: %s",
                              self._name, path, exc)
            return False

        reservation_id: str = reservation_data.get("id") or os.path.basename(path)
        self.logger.debug("%s: expired reservation %s", self._name, reservation_id)
        return True

    # ---------------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------------

    def _path_for(self, reservation_id: str) -> str:
        """
        Local-file analog of S3RetryUtil.get_obj_key_for_reservation.
        """
        if not isinstance(reservation_id, str) or not reservation_id.strip():
            raise ValueError("reservation_id must be a non-empty string")

        reservation_id = reservation_id.strip()
        for sep in (os.sep, os.altsep):
            if sep and sep in reservation_id:
                raise ValueError("reservation_id must not contain path separators")

        base_path = os.path.abspath(self.base_path)
        candidate = os.path.abspath(
            os.path.join(base_path, f"{reservation_id}{self.RESERVATION_FILE_SUFFIX}")
        )
        if os.path.commonpath([base_path, candidate]) != base_path:
            raise ValueError(f"Invalid reservation_id {reservation_id!r}: resolves outside base_path")

        return candidate
