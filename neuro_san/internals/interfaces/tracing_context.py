
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
from __future__ import annotations

from typing import Any
from typing import Dict

from neuro_san.internals.interfaces.run_target import RunTarget


class TracingContext(RunTarget):
    """
    Interface for a single request's tracing needs.
    """

    async def run_it(self, inputs: Any) -> Any:
        """
        Entry point method for the run.

        :param inputs: A list of inputs from the user.
        :return: The outputs of the run.
        """
        raise NotImplementedError

    def clone(self) -> TracingContext:
        """
        Creates a copy the tracing context.

        :return: A clone of the tracing context.
        """
        raise NotImplementedError

    def augment_config(self, runnable_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Augment the configuration however the implementation sees fit (if at all).
        :param runnable_config: The config for the runnable
        :return: The augmented config
        """
        raise NotImplementedError

    async def flush(self):
        """
        Flush the tracing context.
        """
        raise NotImplementedError
