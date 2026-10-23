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

from argparse import Namespace
from threading import Event
from typing import Optional

from tests.load_tests.prompts.agent_profile import AgentProfile
from tests.load_tests.traffic.runner import TrafficRunner


class TrafficRunnerTestHelpers:
    """
    Test setup shared by the TrafficRunner and Heartbeat tests. The module and class names keep pytest from
    collecting them, and importing this class does not run any test class again.
    """

    @staticmethod
    def create_runner(stage_timeout_seconds: Optional[float] = None) -> TrafficRunner:
        """
        Return a runner over a one-prompt profile with every argument run_one_http() and run_stage() read.

        :param stage_timeout_seconds: Seconds after which run_stage() kills unfinished requests, or None
        :return: The runner
        """
        profile: AgentProfile = AgentProfile("x", {"prompts": ["p"]})
        args: Namespace = Namespace(
            same_prompt=False, allow_caching=False, host="localhost", port=8080, https=False, agent="x",
            chat_filter="maximal", request_timeout=5.0, idle_timeout=5.0, include_tokens=False,
            stage_timeout=stage_timeout_seconds)
        stop_event: Event = Event()
        return TrafficRunner(args, profile, stop_event)
