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

from functools import partial
from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional
from typing import TypeVar

from psutil import AccessDenied
from psutil import NoSuchProcess
from psutil import Process

from tests.load_tests.monitoring.process_read_error import ProcessReadError

# The type one psutil read returns: TrackedProcess._read() returns the same type as the call it wraps.
ReadResult = TypeVar("ReadResult")


class TrackedProcess:
    """
    One local process the load test measures: the neuro-san server, the mock LLM server or the load test client.

    This class and ResourceMonitor (whole-system values) are the only load test classes that use psutil.
    Every read raises ProcessReadError when the process has exited or access to it is denied.
    """

    def __init__(self, pid: Optional[int] = None) -> None:
        """
        Attach to a running process.

        :param pid: Process ID, or None for the current process (the load test client)
        :raises ProcessReadError: When no process has that ID or access to it is denied
        """
        self._process: Process = TrackedProcess._read(partial(Process, pid))

    def get_pid(self) -> int:
        """
        :return: The process ID
        """
        return self._process.pid

    def is_running(self) -> bool:
        """
        :return: True while the process is still running
        """
        return TrackedProcess._read(self._process.is_running)

    def num_threads(self) -> int:
        """
        :return: The number of threads of the process
        """
        return TrackedProcess._read(self._process.num_threads)

    def memory_info(self) -> Any:
        """
        :return: psutil's private pmem named tuple (it has no public type to name); its rss is in bytes
        """
        return TrackedProcess._read(self._process.memory_info)

    def memory_full_info(self) -> Any:
        """
        :return: psutil's private pfullmem named tuple (it has no public type to name); rss and swap are in bytes
        """
        return TrackedProcess._read(self._process.memory_full_info)

    def cpu_times(self) -> Any:
        """
        :return: psutil's private pcputimes named tuple (it has no public type to name); user and system are seconds
        """
        return TrackedProcess._read(self._process.cpu_times)

    def cpu_percent(self, interval_seconds: float) -> float:
        """
        :param interval_seconds: Seconds to sample the CPU use over
        :return: CPU use of the process in percent of one core
        """
        return TrackedProcess._read(partial(self._process.cpu_percent, interval=interval_seconds))

    def file_descriptor_count(self) -> int:
        """
        :return: Open file descriptors; on Windows, which has no file descriptors, open handles
        """
        try:
            return TrackedProcess._read(self._process.num_fds)
        except AttributeError:
            return TrackedProcess._read(self._process.num_handles)

    def net_connections(self) -> List[Any]:
        """
        :return: psutil's private pconn named tuples (they have no public type to name), one per open connection
        """
        return TrackedProcess._read(self._process.net_connections)

    def child_count(self) -> int:
        """
        :return: The number of child processes
        """
        children: List[Process] = TrackedProcess._read(self._process.children)
        child_count: int = len(children)
        return child_count

    def cmdline(self) -> List[str]:
        """
        :return: The command line of the process, one item per argument
        """
        return TrackedProcess._read(self._process.cmdline)

    def environ(self) -> Dict[str, str]:
        """
        :return: The environment variables of the process
        """
        return TrackedProcess._read(self._process.environ)

    def cwd(self) -> str:
        """
        :return: The working directory of the process
        """
        return TrackedProcess._read(self._process.cwd)

    @staticmethod
    def _read(reader: Callable[[], ReadResult]) -> ReadResult:
        """
        Call one psutil read and turn its process errors into ProcessReadError, so callers need no psutil import.

        :param reader: The psutil call, with its arguments already bound
        :return: What the call returns
        :raises ProcessReadError: When the process has exited or access to it is denied
        """
        try:
            return reader()
        except (NoSuchProcess, AccessDenied) as error:
            raise ProcessReadError(str(error)) from error
