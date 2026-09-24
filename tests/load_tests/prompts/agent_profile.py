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
from typing import Any
from typing import Dict
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
        """Return the JSON profile's sly_data keys that must come back non-empty.

        Only JSON profiles carry this; AgentProfileFactory turns it into
        the equivalent `responses` block, which is what TrafficRunner
        checks. Hocon profiles state their checks in `responses` directly.
        """
        return self._data.get("success_fields", [])

    @property
    def responses(self) -> List[Dict[str, Any]]:
        """Return the per-prompt response checks, parallel to prompts.

        Each entry is a test-case hocon "response" block (text /
        structure / sly_data with AgentEvaluator checks such as
        keywords, value, not_value, gist). See
        docs/test_case_hocon_reference.md. A JSON profile gets one
        block, built from its success_fields, shared by all prompts.
        """
        return self._data.get("responses", [])

    @property
    def failure_patterns(self) -> List[str]:
        """Return substrings that indicate a failed response.

        When any pattern is found in the answer text, a request that would
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
        base_prompt = prompts[self._pool_index(request_id, same_prompt, len(prompts))]
        if allow_caching:
            return base_prompt
        # The suffix makes every prompt unique, so no cache along the
        # path (LLM prompt cache, agent network, proxy) can serve the
        # response and the run measures real work, not cache hits.
        return f"{base_prompt} (request {request_id})"

    def get_response(self, request_id, same_prompt=False) -> Dict[str, Any]:
        """Return the response checks for the prompt get_prompt() gives request_id."""
        responses = self.responses
        if not responses:
            return {}
        return responses[self._pool_index(request_id, same_prompt, len(responses))]

    @staticmethod
    def _pool_index(request_id, same_prompt, size) -> int:
        """Index into a per-prompt pool: first entry in same_prompt mode, else cycle."""
        if same_prompt:
            return 0
        return request_id % size
