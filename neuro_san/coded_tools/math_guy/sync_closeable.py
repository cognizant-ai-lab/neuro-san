
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

from logging import getLogger
from logging import Logger


class SyncCloseable:
    """
    A simple object used to test the synchronous close()-ing of objects on sly_data.
    """

    def close(self):
        """
        Close the object
        """
        logger: Logger = getLogger(self.__class__.__name__)
        logger.info("sync close() called")
