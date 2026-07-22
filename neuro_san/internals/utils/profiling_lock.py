
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

from __future__ import annotations

from typing import List
from typing import Tuple

from logging import getLogger
from logging import Logger
from os import environ
from threading import Lock
from time import perf_counter


class ProfilingLock:
    """
    Class that adds some profiling information to a synchronous lock.
    """

    INITIAL_STATE: str = "waiting for lock"

    def __init__(self, name: str, lock_in: Lock = None):
        """
        Constructor

        :param name: The name of the lock
        :param lock_in: The lock to wrap. If no lock is provided, a new one will be created.
        """
        self.name: str = name
        self.lock: Lock = lock_in
        if self.lock is None:
            self.lock = Lock()

        self.logger: Logger = getLogger(name)
        self.stats_in_play: List[Tuple[str, float]] = []
        self.show_stats: bool = environ.get("AGENT_LOCK_PROFILING", "false").lower() == "true"

    def __enter__(self) -> ProfilingLock:
        """
        Acquire the lock
        """
        stats: List[Tuple[str, float]] = []
        self.acquire(stats)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """
        Release the lock
        :return: True to suppress exception. False or None to propagate exception.
        """
        self.release()
        return False

    def acquire(self, stats: List[Tuple[str, float]] = None):
        """
        Acquire the lock
        """
        if stats is None:
            stats = []
        self.add_stat(self.INITIAL_STATE, stats)
        self.lock.acquire()
        self.add_stat("acquired lock", stats)
        self.stats_in_play = stats

    def add_stat(self, key: str, stats: List[Tuple[str, float]] = None):
        """
        Add a stat to the lock
        """
        if stats is None:
            stats = self.stats_in_play
        stats.append((key, perf_counter()))

    def release(self):
        """
        Release the lock
        """
        stats: List[Tuple[str, float]] = self.stats_in_play
        self.stats_in_play = []

        self.lock.release()

        self.add_stat("released lock", stats)
        if self.show_stats:
            self.print_stats(stats)

    def print_stats(self, stats: List[Tuple[str, float]]):
        """
        Print the stats
        """
        first_time: float = 0.0
        item: Tuple[str, float] = None
        for item in stats:
            key: str = item[0]
            time: float = item[1]
            if first_time == 0.0:
                first_time = time
            else:
                self.logger.info("%s:%s in %f secs", self.name, key, time - first_time)
