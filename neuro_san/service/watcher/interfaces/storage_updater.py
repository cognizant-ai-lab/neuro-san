
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

from neuro_san.service.watcher.interfaces.startable import Startable


class StorageUpdater(Startable):
    """
    Interface for specific updating jobs that the Watcher performs.
    """

    def start(self):
        """
        Perform start up.
        """
        raise NotImplementedError

    def get_update_period_in_seconds(self) -> int:
        """
        :return: An int describing how long this updater ideally wants to go between
                calls to update_storage().
        """
        raise NotImplementedError

    def needs_updating(self, time_now_in_seconds: float) -> bool:
        """
        :param time_now_in_seconds: The current time in seconds.
                    We expect this to be from time.time()
        :return: True if this instance needs updating. False otherwise.
        """
        raise NotImplementedError

    def update_storage(self):
        """
        Perform an update
        """
        raise NotImplementedError
