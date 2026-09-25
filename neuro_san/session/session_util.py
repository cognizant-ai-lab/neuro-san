
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

from typing import Any
from typing import Optional

from logging import getLogger
from logging import Logger
from os import environ


class SessionUtil:
    """
    Static utility class with common session policy: currently the MAX_AGENTS_FROM_EXTERNAL_SERVER
    bound on how many entries to take from another server's agent/tool listing.
    """

    MAX_AGENTS_ENV_VAR: str = "MAX_AGENTS_FROM_EXTERNAL_SERVER"

    @staticmethod
    def get_max_agents() -> int:
        """
        Reads MAX_AGENTS_FROM_EXTERNAL_SERVER.  Unset, empty, 0 and negative mean "no limit";
        a non-integer also means "no limit" and is logged as a warning so a typo is not silent.

        :return: The positive limit, or 0 meaning no limit
        """
        max_agents_str: Optional[str] = environ.get(SessionUtil.MAX_AGENTS_ENV_VAR)
        if max_agents_str is None or max_agents_str.strip() == "":
            return 0

        max_agents: int = 0
        try:
            max_agents = int(max_agents_str)
        except ValueError:
            logger: Logger = getLogger(SessionUtil.__name__)
            logger.warning("Ignoring %s=%r: not an integer, so no limit is applied to server listings",
                           SessionUtil.MAX_AGENTS_ENV_VAR, max_agents_str)
            return 0

        # Negative values are documented as meaning "unlimited", same as 0.
        return max(max_agents, 0)

    @staticmethod
    def limit_agents_list(agents_list: Any) -> Any:
        """
        Limits an agent/tool listing from a server to at most MAX_AGENTS_FROM_EXTERNAL_SERVER
        entries.  Typed Any because the value comes straight from the server's JSON; anything
        that is not a list is returned unchanged.

        :param agents_list: List of agents/tools as returned by the server
        :return: The same list when no limit applies, otherwise the first
                    MAX_AGENTS_FROM_EXTERNAL_SERVER entries (truncation is logged as a warning)
        """
        if not isinstance(agents_list, list):
            return agents_list

        max_agents: int = SessionUtil.get_max_agents()
        if max_agents <= 0 or len(agents_list) <= max_agents:
            return agents_list

        logger: Logger = getLogger(SessionUtil.__name__)
        logger.warning("%s=%d: considering only the first %d of the %d entries the server listed",
                       SessionUtil.MAX_AGENTS_ENV_VAR, max_agents, max_agents, len(agents_list))
        return agents_list[:max_agents]
