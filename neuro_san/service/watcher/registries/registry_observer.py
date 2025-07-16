
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

from typing import Tuple

from neuro_san.service.watcher.interfaces.startable import Startable


class RegistryObserver(Startable):
    """
    Interface for specific kinds of filesystem observing
    """

    def start(self):
        """
        Start running observer
        """
        raise NotImplementedError

    def reset_event_counters(self) -> Tuple[int, int, int]:
        """
        Reset event counters and return current counters.
        """
        raise NotImplementedError
