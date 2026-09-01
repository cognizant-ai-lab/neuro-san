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

"""Agent profile loader — reads agent-specific prompts and configuration."""

import json
import logging
import os
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
        return f"{base_prompt} (request {request_id})"

    @classmethod
    def load(cls, agent_name, profile_path=None, project_root=None) -> "AgentProfile":
        """Load an agent profile from a JSON file.

        Search order:
        1. --profile-path directory: look for {base}.json there
        2. ./profiles/{agent_name}.json then ./profiles/{base}.json
        3. {project_root}/tests/load_tests/prompts/profiles/{name}.json
           where project_root comes from --project-root or PYTHONPATH
        4. Not found → abort

        When agent_name includes a prefix (e.g. basic/hello_world),
        the base name (hello_world) is tried as a fallback so
        --profile-path is not required for prefixed agents.
        """
        agent_base = agent_name.rsplit("/", 1)[-1]

        if profile_path:
            if os.path.isfile(profile_path):
                logger.error(
                    "--profile-path should be a directory, not a "
                    "file.\n"
                    "  Got: %s\n"
                    "  Try: --profile-path %s",
                    profile_path, os.path.dirname(profile_path),
                )
                raise SystemExit(1)
            candidate = os.path.join(profile_path, f"{agent_base}.json")
            if not os.path.isfile(candidate):
                logger.error(
                    "Profile not found: %s\n"
                    "  --profile-path directory: %s\n"
                    "  Expected file: %s.json\n"
                    "  Aborting.",
                    candidate, profile_path, agent_base,
                )
                raise SystemExit(1)
            return cls._load_from_file(agent_name, candidate)

        searched = []

        # Search in the built-in profiles directory next to this module
        profiles_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "profiles",
        )
        for name in (agent_name, agent_base):
            candidate = os.path.join(profiles_dir, f"{name}.json")
            searched.append(candidate)
            if os.path.isfile(candidate):
                return cls._load_from_file(agent_name, candidate)

        # Resolve project root: --project-root flag → PYTHONPATH fallback
        resolved_root = cls._resolve_project_root(project_root)
        if resolved_root:
            for name in (agent_name, agent_base):
                candidate = os.path.normpath(os.path.join(
                    resolved_root, "tests", "load_tests",
                    "prompts", "profiles", f"{name}.json",
                ))
                searched.append(candidate)
                if os.path.isfile(candidate):
                    return cls._load_from_file(agent_name, candidate)

        logger.error(
            "No profile found for agent '%s'.\n"
            "Searched:\n%s\n"
            "Create a profile JSON or use --profile-path to specify one.\n"
            "Aborting.",
            agent_name,
            "".join(f"  - {p}\n" for p in searched),
        )
        raise SystemExit(1)

    @classmethod
    def _resolve_project_root(cls, project_root=None) -> Optional[str]:
        """Resolve the project root directory.

        Priority: explicit --project-root → first entry in PYTHONPATH.
        """
        if project_root:
            return os.path.abspath(project_root)

        python_path = os.environ.get("PYTHONPATH")
        if python_path:
            first_entry = python_path.split(os.pathsep)[0]
            if os.path.isdir(first_entry):
                return os.path.abspath(first_entry)

        return None

    @classmethod
    def _load_from_file(cls, agent_name, path) -> "AgentProfile":
        """Load profile data from a JSON file."""
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data: Dict[str, Any] = json.load(fh)
            logger.info("Loaded agent profile: %s", path)
            return cls(agent_name, data)
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Failed to load profile %s: %s\nAborting.", path, exc)
            raise SystemExit(1) from exc
