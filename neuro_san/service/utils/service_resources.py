
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
from typing import Any
from typing import Dict
from typing import Set
from typing import Tuple
import os
import resource
import socket
import stat
import sys
import psutil


class ServiceResources:
    """
    Class provides utility methods to monitor usage of service run-time resources,
    like file descriptors and TCP connections.
    """

    @classmethod
    def iter_fds(cls):
        """
        Iterator for all open file descriptors in current process:
        """
        fd_dir = "/proc/self/fd" if sys.platform.startswith("linux") else "/dev/fd"
        for name in os.listdir(fd_dir):
            try:
                fd = int(name)
            except Exception:  # pylint: disable=broad-exception-caught
                continue
            yield fd

    @classmethod
    def classify_fds(cls) -> Dict[str, int]:
        """
        Returns dictionary with counts for different kinds of file descriptors
        currently open for our process
        """
        p = psutil.Process()

        # Build maps of socket FDs for finer classification
        inet_fds = {c.fd for c in p.connections(kind="inet")}  # tcp/udp
        unix_fds = {c.fd for c in p.connections(kind="unix")}  # unix sockets

        fd_dict: Dict[str, int] = {}
        total_fds: int = 0
        for fd in cls.iter_fds():
            try:
                st = os.fstat(fd)
            except OSError:
                continue  # fd may be closed already
            mode = st.st_mode

            if stat.S_ISREG(mode):
                kind = "regular_file"
            elif stat.S_ISSOCK(mode):
                if fd in inet_fds:
                    kind = "socket_inet"
                elif fd in unix_fds:
                    kind = "socket_unix"
                else:
                    kind = "other"
            elif stat.S_ISFIFO(mode):
                kind = "fifo_pipe"
            else:
                kind = "other"

            total_fds = total_fds+1
            count = fd_dict.get(kind, 0)
            fd_dict[kind] = count+1
        fd_dict["total"] = total_fds
        return fd_dict

    @classmethod
    def get_fd_usage(cls) -> Tuple[Dict[str, int], int, int]:
        """
        :return: tuple of 3 values:
            dictionary for kinds of file descriptors in use;
            soft limit for file descriptors for current process;
            hard limit for file descriptors for current process;
        """
        p = psutil.Process()
        fd_dict: Dict[str, int] = cls.classify_fds()
        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        return fd_dict, soft, hard

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

    @classmethod
    def classify_outbound_sockets(cls, outbound_tcp) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for conn in outbound_tcp:
            sock_addr: str = f"{conn.raddr}"
            if sock_addr not in result:
                result[sock_addr] = {}
            sock_status: str = f"{conn.status}"
            status_count: int = result[sock_addr].get(sock_status, 0)
            result[sock_addr][sock_status] = status_count+1
        return result

    @classmethod
    def classify_sockets(cls, server_port: int):
        p = psutil.Process()
        tcp = p.connections(kind="tcp")

        inbound_listen = []
        inbound_accepted = []
        outbound_tcp = []

        for c in tcp:
            lport = c.laddr.port if c.laddr else None
            # LISTEN sockets on the server port(s)
            if c.status == psutil.CONN_LISTEN and lport==server_port:
                inbound_listen.append(c)
                continue
            # Accepted inbound sockets on the server port(s)
            if lport==server_port and c.status != psutil.CONN_LISTEN:
                inbound_accepted.append(c)
                continue
            # Everything else TCP is outbound (client) from this process
            outbound_tcp.append(c)

        return {
            "inbound_listen": len(inbound_listen),
            "inbound_accepted": len(inbound_accepted),
            "outbound_tcp": cls.classify_outbound_sockets(outbound_tcp)
        }

    @classmethod
    def _fd_target(cls, fd: int) -> str | None:
        """Best-effort: show what the fd points to via /proc or /dev/fd."""
        try:
            path = f"/proc/self/fd/{fd}" if sys.platform.startswith("linux") else f"/dev/fd/{fd}"
            return os.readlink(path)
        except Exception:
            return None

    @classmethod
    def classify_unix_sockets(cls):
        """
        Classify Unix sockets open for current process
        """
        p = psutil.Process()
        # psutil: kind="unix" returns only AF_UNIX sockets
        conns = p.connections(kind="unix")

        items = []  # list of dicts with details per socket

        for c in conns:
            fd = getattr(c, "fd", None)
            addr = c.laddr  # For AF_UNIX: this is typically a string path or ''/None
            s_type = {
                socket.SOCK_STREAM: "STREAM",
                socket.SOCK_DGRAM: "DGRAM",
                socket.SOCK_SEQPACKET: "SEQPACKET",
            }.get(getattr(c, "type", None), str(getattr(c, "type", None)))

            # Determine category
            if isinstance(addr, str) and addr:
                if sys.platform.startswith("linux") and addr.startswith("\x00"):
                    kind = "abstract"  # Linux abstract namespace
                    disp = f"@{addr[1:]}"  # pretty form (tools often show '@name')
                else:
                    kind = "named"  # has filesystem pathname
                    disp = addr
            else:
                # No address/path; typical for socketpair()/unnamed sockets
                kind = "unnamed"
                disp = ""

            fd_link = cls._fd_target(fd) if fd is not None else None

            items.append({
                "fd": fd,
                "kind": kind,
                "type": s_type,
                "address": disp,
                "fd_target": fd_link,  # e.g., "socket:[12345]" (Linux) or "-> socket" (macOS)
            })

        return items

    # if __name__ == "__main__":
    #     items, counts = classify_unix_sockets()
    #
    #     total = sum(counts.values())
    #     print(f"Unix domain sockets in this process: {total}")
    #     for k in ("named", "abstract", "unnamed"):
    #         if counts[k]:
    #             print(f"  {k:8s}: {counts[k]}")
    #
    #     # Show a few examples for each category
    #     print("\nExamples:")
    #     by_kind = {"named": [], "abstract": [], "unnamed": []}
    #     for it in items:
    #         if len(by_kind[it["kind"]]) < 5:
    #             by_kind[it["kind"]].append(it)
    #
    #     for k in ("named", "abstract", "unnamed"):
    #         if not by_kind[k]:
    #             continue
    #         print(f"\n{k.upper()}:")
    #         for it in by_kind[k]:
    #             fd = it["fd"]
    #             t = it["type"]
    #             addr = it["address"] or "(no path)"
    #             tgt = it["fd_target"] or "(n/a)"
    #             print(f"  fd={fd} type={t:<9} addr={addr}  target={tgt}")


