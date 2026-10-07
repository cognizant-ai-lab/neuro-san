
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
"""
See class comment for details.
"""

from typing import Any
from typing import Callable
from typing import Iterable
from typing import Iterator


class SerialExecutor:
    """
    A stand-in for concurrent.futures executors that runs everything inline.

    Exists for runtimes with no threads or processes to hand out -- Pyodide in
    a browser above all -- where constructing a ThreadPoolExecutor fails
    outright. It presents only the context-manager and map() surface the
    manifest restore path actually uses, deliberately: it is a stand-in for one
    call site, not a general executor.

    Being serial, it is slower than either real option. That is the price of
    running somewhere that cannot be parallel at all.
    """

    def __enter__(self) -> "SerialExecutor":
        """
        :return: This instance, for use as a context manager
        """
        return self

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> bool:
        """
        Nothing to tear down: no workers were ever started.

        :param exc_type: The exception type, if any
        :param exc_value: The exception, if any
        :param traceback: The traceback, if any
        :return: False, so any exception propagates
        """
        return False

    @staticmethod
    def map(function: Callable, *iterables: Iterable) -> Iterator:
        """
        Apply a function across the iterables, one at a time, in this thread.

        Returns a lazy iterator, as the real executors' map() does, so the
        caller consuming it sees the same shape.

        :param function: The function to apply
        :param iterables: The iterables to apply it across
        :return: An iterator over the results
        """
        return map(function, *iterables)
