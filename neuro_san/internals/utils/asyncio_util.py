
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

from asyncio import AbstractEventLoop
from asyncio import get_running_loop

from leaf_common.asyncio.asyncio_executor import AsyncioExecutor


class AsyncioUtil:
    """
    Utilities to deal with asyncio execution
    """

    @staticmethod
    def is_running_in_executor(executor: AsyncioExecutor) -> bool:
        """
        Determines whether the current thread is running the event loop of the given executor.
        A synchronous call that blocks on a coroutine scheduled onto that same loop never completes,
        so callers use this to detect that case before it hangs.

        :param executor: The AsyncioExecutor whose event loop is checked
        :return: True if the event loop running on the current thread is the executor's event loop.
                 False if no event loop is running on the current thread, or if it is a different loop.
        """
        running_loop: AbstractEventLoop = None
        try:
            running_loop = get_running_loop()
        except RuntimeError:
            # No event loop is running on the current thread
            return False

        in_executor: bool = running_loop is executor.get_event_loop()
        return in_executor
