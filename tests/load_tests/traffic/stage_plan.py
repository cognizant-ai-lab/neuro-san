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

from typing import Optional


class StagePlan:
    """
    Data-only description of one load-test stage: how many requests to fire,
    with how many workers, how they are numbered, and where their output goes.
    """

    def __init__(self, num_requests: int, max_workers: int, global_offset: int, output_dir: Optional[str]) -> None:
        """
        :param num_requests: Requests to fire in this stage
        :param max_workers: Thread pool size
        :param global_offset: Request number of the first request across the whole run
        :param output_dir: Directory for per-request output files, or None
        """
        self._num_requests: int = num_requests
        self._max_workers: int = max_workers
        self._global_offset: int = global_offset
        self._output_dir: Optional[str] = output_dir

    def get_num_requests(self) -> int:
        """
        :return: Requests to fire in this stage
        """
        return self._num_requests

    def get_max_workers(self) -> int:
        """
        :return: Thread pool size
        """
        return self._max_workers

    def get_global_offset(self) -> int:
        """
        :return: Request number of the first request across the whole run
        """
        return self._global_offset

    def get_output_dir(self) -> Optional[str]:
        """
        :return: Directory for per-request output files, or None
        """
        return self._output_dir
