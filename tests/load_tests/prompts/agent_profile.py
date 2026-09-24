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

"""Agent profile — agent-specific prompts and response checks.

Built by AgentProfileFactory; this class only carries the data.
"""

import logging
from typing import List
from typing import Optional

logger = logging.getLogger(__name__)


class AgentProfile:
    """Configuration profile for a specific agent under test."""

    def __init__(self, agent_name, profile_data) -> None:
        """Initialize the profile from a loaded profile dict."""
        self.agent_name = agent_name
        self._data = profile_data

    @property
    def prompts(self) -> List[str]:
        """Return the list of prompts for this agent."""
        return self._data.get("prompts", [])

    @property
    def estimated_tokens_per_request(self) -> Optional[int]:
        """Return the estimated token usage per request, or None if unknown."""
        return self._data.get("estimated_tokens_per_request")

    @property
    def primary_start_pattern(self) -> str:
        """Return regex pattern to identify primary request starts in server log."""
        default = f"Start {self.agent_name}/streaming_chat"
        return self._data.get("primary_start_pattern", default)

    @property
    def primary_finish_pattern(self) -> str:
        """Return regex pattern to identify primary request completions in server log."""
        default = f"Finish {self.agent_name}/streaming_chat"
        return self._data.get("primary_finish_pattern", default)

    @property
    def success_fields(self) -> List[str]:
        """Return list of stdout fields that must be present for success.

        For agent_network_designer: ["reservation_id", "agent_network_name"]
        For generic agents: [] (just check exit code)
        """
        return self._data.get("success_fields", [])

    @property
    def failure_patterns(self) -> List[str]:
        """Return substrings that indicate a failed response.

        When any pattern is found in stdout, a request that would
        otherwise be marked CREATED is downgraded to FAILED.  This
        catches cases where the server returns an error message
        inside a successful HTTP 200 response (e.g. missing API key).
        """
        return self._data.get("failure_patterns", [])

    def get_prompt(self, request_id, same_prompt=False,
                   allow_caching=False) -> str:
        """Return the prompt for a given request.

        In same_prompt mode, always returns the first prompt.
        In varied mode, cycles through the pool and appends the request_id.
        The request_id suffix keeps every prompt unique so that no
        cache along the path (LLM prompt cache, agent network, proxy)
        can serve the response.  In allow_caching mode the suffix is
        dropped, so requests that reuse a pool prompt are eligible
        for those caches.
        """
        prompts = self.prompts
        if not prompts:
            logger.error(
                "Agent profile '%s' has an empty prompts list.\n"
                "  Add at least one prompt to the profile JSON.\n"
                "  Aborting.",
                self.agent_name,
            )
            raise SystemExit(1)
        if same_prompt:
            return prompts[0]
        base_prompt = prompts[request_id % len(prompts)]
        if allow_caching:
            return base_prompt
        # The suffix makes every prompt unique, so no cache along the
        # path (LLM prompt cache, agent network, proxy) can serve the
        # response and the run measures real work, not cache hits.
        return f"{base_prompt} (request {request_id})"
