
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


class Startable:
    """
    Interface for objects which have a specific starting phase.
    """

    def start(self):
        """
        Perform start up.
        """
        raise NotImplementedError

    def stop(self):
        """
        Perform steps to stop/shut-down
        By default this does nothing
        """
