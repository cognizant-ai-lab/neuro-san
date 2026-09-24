
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
    Static utility class with common session policy.

    Currently this holds the MAX_AGENTS_FROM_EXTERNAL_SERVER policy, which bounds how many
    entries a client-side session considers from an agent/tool listing returned by the
    server it was pointed at.  It is what answers the SAST "Unchecked Input for Loop
    Condition" reports against McpServiceAgentSession and HttpConciergeSession
    (see neuro_san/deploy/SAST_FALSE_POSITIVES.md).  Only client code such as agent_cli
    reaches those sessions; the neuro-san server itself never consults this variable.
    """

    MAX_AGENTS_ENV_VAR: str = "MAX_AGENTS_FROM_EXTERNAL_SERVER"

    @staticmethod
    def get_max_agents() -> int:
        """
        Reads the MAX_AGENTS_FROM_EXTERNAL_SERVER environment variable.

        Unset, empty, zero and negative values all mean "no limit".  A value that is not an
        integer also means "no limit", and is logged as a warning: it is most likely a typo
        in a setting somebody meant to turn on, and silently ignoring it would leave them
        believing the limit is in force.

        :return: The positive limit the variable holds, or 0 meaning no limit
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
        entries when that variable holds a positive integer.

        The parameter and return are typed Any rather than List because the value comes
        straight out of a server's JSON and this method promises to hand back whatever it was
        given when that is not a list.

        :param agents_list: List of agents/tools as returned by the server.  Anything that is
                    not a list (None, or an otherwise malformed payload) is returned unchanged
                    rather than raising from a slice here; the caller sees the same shape it
                    would have seen with no limit set.
        :return: The same list when there is no limit or the list already fits within it,
                    otherwise a copy holding only the first MAX_AGENTS_FROM_EXTERNAL_SERVER
                    entries.  Truncation is logged as a warning so that an agent missing from
                    the result can be traced back to this setting.
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
