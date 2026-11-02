
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

# inspect generates its CO_* flag constants at import time, so pylint cannot see them.
from inspect import CO_ASYNC_GENERATOR  # pylint: disable=no-name-in-module
from inspect import CO_COROUTINE  # pylint: disable=no-name-in-module
from inspect import currentframe
from types import CodeType
from types import FrameType


class AsyncioUtil:
    """
    Utilities to deal with asyncio execution
    """

    # Code flags that mark a frame as executing inside an async def or async generator
    ASYNC_CODE_FLAGS: int = CO_COROUTINE | CO_ASYNC_GENERATOR

    @staticmethod
    def is_called_by_async_method() -> bool:
        """
        Determines whether any frame up the current call stack is executing an async method.
        Frames are checked via their code flags, so module-level functions, instance methods,
        class methods and static methods are all detected.

        :return: True if an async method is anywhere up the current call stack.
                 False if the call stack is entirely synchronous.
        """
        current_frame: FrameType = currentframe()
        frame: FrameType = current_frame.f_back
        try:
            # Walk up the call stack from the immediate caller
            while frame is not None:
                f_code: CodeType = frame.f_code
                co_flags: int = f_code.co_flags
                if co_flags & AsyncioUtil.ASYNC_CODE_FLAGS:
                    return True
                frame = frame.f_back
        finally:
            # Drop the frame reference to avoid a reference cycle
            del frame

        return False
