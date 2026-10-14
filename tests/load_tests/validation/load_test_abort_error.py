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


class LoadTestAbortError(Exception):
    """
    Raised by a load-test check to stop the run before it starts.

    The validators log the reason and raise this instead of exiting.
    Only the __main__ entry point, LoadTestOrchestrator.main(), turns it
    into a process exit with get_exit_code().
    """

    def __init__(self, exit_code: int) -> None:
        """
        Store the exit code for the __main__ entry point.

        :param exit_code: 1 when a check failed, 0 when the user declined the run
        """
        super().__init__(exit_code)
        self._exit_code: int = exit_code

    def get_exit_code(self) -> int:
        """
        Return the process exit code for this abort.

        :return: 1 when a check failed, 0 when the user declined the run
        """
        return self._exit_code
