
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
See class definition for comments.
"""
import os
import sys
import stat
from typing import Any
from typing import Dict
from typing import Iterable
from typing import List
from typing import Optional
from typing import Tuple
import psutil

# Unix-only
try:
    # pylint: disable=invalid-name
    import resource  # not available on Windows
except Exception:  # pylint: disable=broad-exception-caught
    resource = None


class ServiceResources:
    """
    Class provides utility methods to monitor usage
    of service run-time resources,
    like:
    - Unix/macOS: file descriptors (FDs) by type
    - Windows: OS handles breakdown (files vs INET sockets) + total handles
    """
    on_unix: bool = sys.platform.startswith("linux")
    on_macos: bool = sys.platform.startswith("darwin")
    on_windows: bool = sys.platform.startswith("win")

    # High watermark for memory usage in bytes since process start (for logging purposes).
    # Keyed by (PID, create_time) to handle PID reuse correctly.
    # None key represents the current process.
    _max_memory_used_bytes: Dict[Optional[Tuple[int, float]], float] = {}

    # ---------------------------
    # POSIX helpers (Linux/macOS)
    # ---------------------------
    @classmethod
    def _iter_fds_posix(cls, pid: Optional[int] = None):
        """
        Iterator over numeric FDs for a process (Unix/macOS).
        :param pid: target process ID, or None for the current process.
        """
        if cls.on_windows:
            # Windows does not have /dev/fd or /proc; FD enumeration is
            # handled by _classify_handles_windows via the classify_fds router.
            return
        if pid is not None and cls.on_unix:
            # Linux: external process FDs are visible via /proc/<pid>/fd
            fd_dir = f"/proc/{pid}/fd"
        elif pid is not None:
            # Non-Linux (macOS, BSD, etc.): /dev/fd only lists the current
            # process's FDs; there is no /proc/<pid>/fd equivalent.
            # Callers should fall back to psutil.Process(pid).num_fds().
            return
        elif cls.on_unix:
            # Linux: /proc/self/fd is a procfs symlink to the current process's FDs.
            # See: https://man7.org/linux/man-pages/man5/proc.5.html
            fd_dir = "/proc/self/fd"
        else:
            # Non-Linux POSIX (macOS, BSD, etc.): /dev/fd lists the current
            # process's open file descriptors. On unsupported platforms, the
            # os.listdir below will fail and the except clause returns gracefully.
            # See: https://developer.apple.com/library/archive/documentation/
            #   System/Conceptual/ManPages_iPhoneOS/man4/fd.4.html
            fd_dir = "/dev/fd"
        try:
            names = os.listdir(fd_dir)
        except Exception:  # pylint: disable=broad-exception-caught
            # directory may not exist in some rare environments
            return
        for name in names:
            try:
                fd = int(name)
            except Exception:  # pylint: disable=broad-exception-caught
                continue
            yield fd

    @classmethod
    def _classify_fds_posix(cls, pid: Optional[int] = None) -> Dict[str, int]:  # pylint: disable=too-many-branches
        """
        Returns counts by FD kind on Unix/macOS:
          regular_file, socket_inet, socket_unix, fifo_pipe, other, total
        :param pid: target process ID, or None for the current process.

        For external PIDs on macOS, per-FD classification is not possible
        (no /proc filesystem). Falls back to psutil.Process(pid).num_fds()
        for a total count only.
        """
        p = cls._get_process(pid)

        # On macOS with an external PID, we cannot enumerate individual FDs.
        # Fall back to psutil for a simple total count.
        if pid is not None and not cls.on_unix:
            fd_dict: Dict[str, int] = {
                "regular_file": 0,
                "socket_inet": 0,
                "socket_unix": 0,
                "fifo_pipe": 0,
                "other": 0,
                "total": p.num_fds(),
            }
            return fd_dict

        # Maps of socket FDs to distinguish AF_INET vs AF_UNIX
        try:
            inet_fds = {c.fd for c in p.net_connections(kind="inet")}
        except (AttributeError, Exception):  # pylint: disable=broad-exception-caught
            inet_fds = {c.fd for c in p.connections(kind="inet")}
        try:
            unix_fds = {c.fd for c in p.net_connections(kind="unix")}
        except (AttributeError, Exception):  # pylint: disable=broad-exception-caught
            unix_fds = {c.fd for c in p.connections(kind="unix")}

        fd_dict: Dict[str, int] = {}
        total_fds = 0

        for fd in cls._iter_fds_posix(pid=pid) or ():
            try:
                if pid is not None:
                    # For external processes, stat via /proc/<pid>/fd/<fd> path
                    # because os.fstat(fd) would stat this process's own FD table.
                    st = os.stat(f"/proc/{pid}/fd/{fd}")
                else:
                    st = os.fstat(fd)
            except OSError:
                continue  # fd may have just closed
            mode = st.st_mode

            if stat.S_ISREG(mode):
                kind = "regular_file"
            elif stat.S_ISSOCK(mode):
                if fd in inet_fds:
                    kind = "socket_inet"
                elif fd in unix_fds:
                    kind = "socket_unix"
                else:
                    kind = "other"  # socket but not recognized by psutil maps
            elif stat.S_ISFIFO(mode):
                kind = "fifo_pipe"
            else:
                kind = "other"

            total_fds += 1
            fd_dict[kind] = fd_dict.get(kind, 0) + 1

        fd_dict["total"] = total_fds
        # ensure all expected keys exist (helpful for stable metrics)
        for k in ("regular_file", "socket_inet", "socket_unix", "fifo_pipe", "other"):
            fd_dict.setdefault(k, 0)
        return fd_dict

    # ---------------------------
    # Windows helpers
    # ---------------------------
    @classmethod
    def _classify_handles_windows(cls, pid: Optional[int] = None) -> Dict[str, int]:
        """
        Returns a simplified breakdown on Windows using psutil:

          regular_file   -> len(Process.open_files())
          socket_inet    -> len(Process.net_connections(kind="inet"))
          other_handles  -> num_handles - above_known
          total_handles  -> Process.num_handles()

        Notes:
          * Windows does not expose POSIX FDs; we count OS handles instead.
          * We cannot reliably enumerate every handle type without native WinAPI.
        :param pid: target process ID, or None for the current process.
        """
        p = cls._get_process(pid)

        try:
            total_handles = p.num_handles()  # all handles owned by this process
        except Exception:  # pylint: disable=broad-exception-caught
            total_handles = 0
        files = len(p.open_files())
        # TCP/UDP INET sockets for this process
        # Use net_connections() for psutil>=7.0.0 compatibility;
        # fall back to deprecated connections() for older versions.
        try:
            inet_conns = p.net_connections(kind="inet")
        except (AttributeError, Exception):  # pylint: disable=broad-exception-caught
            inet_conns = p.connections(kind="inet")
        socket_inet = len(inet_conns)

        # We can't see AF_UNIX on Windows (not applicable), FIFO pipes classification requires WinAPI.
        # Derive "other_handles" as the remainder; never let it go negative.
        known = files + socket_inet
        other_handles = max(total_handles - known, 0)

        return {
            "regular_file": files,
            "socket_inet": socket_inet,
            "socket_unix": 0,         # not applicable on Windows
            "fifo_pipe": 0,           # not available via psutil alone
            "other_handles": other_handles,
            "total_handles": total_handles,
        }

    # ---------------------------
    # Public API (cross-platform)
    # ---------------------------
    @staticmethod
    def _get_process(pid: Optional[int] = None) -> psutil.Process:
        """
        Return a psutil.Process for the given PID, or the current process.
        :param pid: target process ID, or None for the current process.
        """
        return psutil.Process(pid) if pid is not None else psutil.Process()

    @classmethod
    def classify_fds(cls, pid: Optional[int] = None) -> Dict[str, int]:
        """
        Cross-platform classification:
          * Unix/macOS: returns per-FD kinds + "total"
          * Windows:    returns per-handle kinds + "total_handles"
        :param pid: target process ID, or None for the current process.
        """
        if cls.on_unix or cls.on_macos:
            return cls._classify_fds_posix(pid=pid)
        if cls.on_windows:
            return cls._classify_handles_windows(pid=pid)
        # Fallback: try POSIX path; if not, return minimal info
        try:
            return cls._classify_fds_posix(pid=pid)
        except Exception:  # pylint: disable=broad-exception-caught
            p = cls._get_process(pid)
            if hasattr(p, "num_fds"):
                return {"total_unknown": p.num_fds()}
            return {"total_unknown": 0}

    @classmethod
    def get_fd_usage(cls, pid: Optional[int] = None) -> Tuple[Dict[str, int], Optional[int], Optional[int]]:
        """
        Returns (counts_dict, soft_limit, hard_limit).

        * Unix/macOS: soft/hard are RLIMIT_NOFILE integers for the current process.
        * Windows:    returns (counts_dict, None, None) since RLIMIT_NOFILE does not apply.
        * External PID: returns (counts_dict, None, None) because resource.getrlimit
          only reads the current process's limits, not the target's.
        :param pid: target process ID, or None for the current process.
        """
        counts = cls.classify_fds(pid=pid)

        # resource.getrlimit returns limits for the current process only.
        # For external PIDs, return None to avoid reporting misleading values.
        if pid is not None:
            return counts, None, None

        if (cls.on_unix or cls.on_macos) and resource is not None:
            soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
            return counts, soft, hard

        # Windows / unknown
        return counts, None, None

    # --- internal helper: get a process's TCP connections, psutil-6-safe ---
    @classmethod
    def _proc_tcp_conns(cls, pid: Optional[int] = None) -> List[Any]:
        """
        Return TCP connections for a process, with a fallback that
        is compatible with psutil 6.x where Process.connections may be deprecated.
        :param pid: target process ID, or None for the current process.
        """
        p = cls._get_process(pid)
        try:
            # Works on psutil <= 5.x and (for now) also on many 6.x installs
            return p.connections(kind="tcp")
        except Exception:  # pylint: disable=broad-exception-caught
            # psutil 6.x style: filter system-wide by pid
            conns = []
            for c in psutil.net_connections(kind="tcp"):
                if getattr(c, "pid", None) == p.pid:
                    conns.append(c)
            return conns

    # --- unchanged external API, but hardened for Windows/psutil variations ---
    @classmethod
    def classify_outbound_sockets(cls, outbound_tcp: Iterable[Any]) -> Dict[str, Any]:
        """
        Classify outbound process socket connections by remote address and status.

        Cross-platform notes:
          * Windows/macOS/Linux all provide per-process TCP connections via psutil.
          * Some entries may have missing raddr (e.g., early handshake) — we bucket those under "(no-remote)".
          * Status names are strings from psutil (e.g., 'ESTABLISHED','TIME_WAIT', etc.).
        """
        result: Dict[str, Dict[str, int]] = {}

        for conn in outbound_tcp:
            # Normalize remote address: "ip:port" or "(no-remote)"
            if conn.raddr:
                try:
                    rip = getattr(conn.raddr, "ip", None)
                    rport = getattr(conn.raddr, "port", None)
                    if rip is None or rport is None:
                        # Fallback to repr if platform provides a different shape
                        sock_addr = str(conn.raddr)
                    else:
                        sock_addr = f"{rip}:{rport}"
                except Exception:  # pylint: disable=broad-exception-caught
                    # Very defensive: some psutil versions/platforms might differ
                    sock_addr = str(conn.raddr)
            else:
                sock_addr = "(no-remote)"

            bucket = result.setdefault(sock_addr, {})
            sock_status: str = str(getattr(conn, "status", "UNKNOWN"))
            bucket[sock_status] = bucket.get(sock_status, 0) + 1

        return result

    @classmethod
    def classify_sockets(cls, server_port: int, pid: Optional[int] = None) -> Dict[str, Any]:
        """
        Classify active sockets bound to the given server port.
        :param server_port: server port
        :param pid: target process ID, or None for the current process.
        :return: dictionary with keys:
           "inbound_listen": number of inbound listening sockets;
           "inbound_accepted": number of accepted inbound connections;
           "outbound_tcp": dictionary describing outbound connections.

        Cross-platform behavior:
          * Works on Linux/macOS/Windows using per-process TCP enumeration.
          * Dual-stack listeners typically appear as separate IPv4/IPv6 LISTEN sockets.
          * Multi-process servers (Tornado server.start(N)) must call this in each worker PID.
        """
        tcp = cls._proc_tcp_conns(pid=pid)

        inbound_listen = 0
        inbound_accepted_list: list = []
        outbound_list: list = []

        for c in tcp:
            lport = c.laddr.port if c.laddr else None
            status = getattr(c, "status", None)

            # LISTEN socket on our server port?
            if status == psutil.CONN_LISTEN and lport == server_port:
                inbound_listen += 1
                continue

            # Accepted inbound socket uses the server port as local port
            if lport == server_port and status != psutil.CONN_LISTEN:
                inbound_accepted_list.append(c)
                continue

            # Everything else is an outbound (client) socket from this process
            outbound_list.append(c)

        return {
            "inbound_listen": inbound_listen,
            "inbound_accepted": len(inbound_accepted_list),
            "outbound_tcp": cls.classify_outbound_sockets(outbound_list),
        }

    @classmethod
    def get_memory_used_mbytes(cls, pid: Optional[int] = None) -> Tuple[float, float]:
        """
        Get the current memory usage of the process in megabytes
        and maximum memory used since process start, and update the maximum if current usage is higher.
        High-water mark is tracked per (PID, create_time) to handle PID reuse
        and avoid cross-contamination when monitoring multiple processes.
        :param pid: target process ID, or None for the current process.
        :return: tuple of (current_memory_used_mbytes, max_memory_used_mbytes)
        """
        p = cls._get_process(pid)
        mem_info = p.memory_info()
        # Key by (pid, create_time) so a recycled PID starts fresh.
        key = (p.pid, p.create_time()) if pid is not None else None
        prev_max = cls._max_memory_used_bytes.get(key, 0.0)
        new_max = max(prev_max, mem_info.rss)
        cls._max_memory_used_bytes[key] = new_max
        # Return memory sizes in megabytes
        return mem_info.rss / (1024 * 1024), new_max / (1024 * 1024)

    @classmethod
    def get_cpu_load(cls, pid: Optional[int] = None) -> float:
        """
        Get the current CPU load percentage of the process.
        Uses the target process's CPU affinity for normalization when available.
        :param pid: target process ID, or None for the current process.
        :return: CPU load percentage over a short interval (e.g., 0.1 seconds)
                 in the range [0.0, 100.0]
        """
        target_pid = pid if pid is not None else 0
        if hasattr(os, "sched_getaffinity"):
            try:
                # sched_getaffinity(pid) returns the set of CPUs the process is allowed
                # to run on. Passing 0 means the current process.
                denom = len(os.sched_getaffinity(target_pid))
            except (ProcessLookupError, PermissionError, OSError):
                # Target process may have exited or be inaccessible.
                # Fall back to system-wide CPU count.
                denom = max(psutil.cpu_count() or 1, 1)
        else:
            denom = max(psutil.cpu_count() or 1, 1)
        cpu_load = cls._get_process(pid).cpu_percent(interval=0.1)
        cpu_load = min(cpu_load / denom, 100.0)
        return cpu_load

    @classmethod
    def get_thread_count(cls, pid: Optional[int] = None) -> int:
        """
        Get the number of threads for the process.
        :param pid: target process ID, or None for the current process.
        :return: number of threads
        """
        p = cls._get_process(pid)
        return p.num_threads()

    @classmethod
    def get_connection_count(cls, pid: Optional[int] = None) -> int:
        """
        Get the number of network connections for the process.
        :param pid: target process ID, or None for the current process.
        :return: number of network connections
        """
        p = cls._get_process(pid)
        return len(p.net_connections())

    @classmethod
    def get_child_count(cls, pid: Optional[int] = None) -> int:
        """
        Get the number of child processes.
        :param pid: target process ID, or None for the current process.
        :return: number of child processes
        """
        p = cls._get_process(pid)
        return len(p.children())

    @classmethod
    def get_snapshot_dict(cls, server_port: int, pid: Optional[int] = None) -> Dict[str, Any]:
        """
        Get a snapshot of current resource usage for logging or metrics.
        :param server_port: server port to classify sockets
        :param pid: target process ID, or None for the current process.
        :return: dictionary with resource usage information
        """
        # Get used file descriptors:
        fd_usage, soft_limit, hard_limit = cls.get_fd_usage(pid=pid)
        mem_used, mem_max = cls.get_memory_used_mbytes(pid=pid)
        cpu_load: float = cls.get_cpu_load(pid=pid)
        snapshot: Dict[str, Any] = {
            "fd_usage": fd_usage,
            "fd_limits": {
                "soft": soft_limit,
                "hard": hard_limit
            },
            "memory_usage_mbytes": {
                "current": mem_used,
                "max_since_start": mem_max
            },
            # Round CPU load to 3 decimal places for more compact output
            "cpu_load": round(cpu_load, 3),
            "socket_usage": cls.classify_sockets(server_port, pid=pid)
        }
        return snapshot
