
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
"""
See class definition for comments.
"""
from typing import Tuple
import resource
import psutil


class ServiceResources:
    """
    Class provides utility methods to monitor usage of service run-time resources,
    like file descriptors and TCP connections.
    """

    @classmethod
    def get_fd_usage(cls) -> Tuple[int, int, int]:
        """
        :return: tuple of 3 integer values:
            number of file descriptors in use;
            soft limit for file descriptors for current process;
            hard limit for file descriptors for current process;
        """
        p = psutil.Process()
        open_fds = p.num_fds()  # includes sockets, pipes, files
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        return open_fds, soft, hard

    @classmethod
    def active_tcp_on_port(cls, port: int) -> int:
        """
        :param port: port number to check;
        :return: number of open connections for this port.
        """
        cnt = 0
        for c in psutil.Process().connections(kind="inet"):
            if c.laddr and c.laddr.port == port and c.status != psutil.CONN_CLOSE:
                cnt += 1
        return cnt
