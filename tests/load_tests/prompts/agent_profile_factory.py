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

"""Factory that builds an AgentProfile from a JSON profile or test-case hocons."""

import json
import logging
import os
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

from leaf_common.persistence.easy.easy_json_persistence import EasyJsonPersistence

from neuro_san.test.util.tests_util import TestsUtil
from tests.load_tests.project_paths import ProjectPaths
from tests.load_tests.prompts.agent_profile import AgentProfile

logger = logging.getLogger(__name__)


class AgentProfileFactory:
    """Builds AgentProfile instances.

    Policy lives here (where the profile comes from, how hocons map to
    profile settings, validation); AgentProfile itself only carries data.
    """

    def create(self, agent_name: str, profile_path: Optional[str] = None,
               project_root: Optional[str] = None,
               hocon_files: Optional[List[str]] = None) -> AgentProfile:
        """Create an AgentProfile.

        When hocon_files is given, the whole profile is built from those
        test-case hocons and no JSON profile is read; see
        _profile_from_hocons() for the hocon keys used.
        Otherwise the profile comes from a JSON file; see
        _find_json_profile() for the search order.
        """
        if hocon_files:
            return AgentProfile(agent_name, self._profile_from_hocons(agent_name, hocon_files))
        path: str = self._find_json_profile(agent_name, profile_path, project_root)
        logger.info("Loaded agent profile: %s", path)
        data: Dict[str, Any] = self._read_json(path)
        data["responses"] = [self._response_from_success_fields(data.get("success_fields", []))]
        return AgentProfile(agent_name, data)

    def _response_from_success_fields(self, success_fields: List[str]) -> Dict[str, Any]:
        """Express a JSON profile's success_fields as a hocon-style response block.

        Each field becomes sly_data.<field>: { not_value: "" }, i.e. the
        ValueAgentEvaluator requires it to be present and non-empty. The
        field is a DictionaryExtractor path from the top of sly_data, so
        a value nested in a list (agent_reservations[0].reservation_id)
        is named by its top-level key (agent_reservations).
        """
        sly_checks: Dict[str, Any] = {field: {"not_value": ""} for field in success_fields}
        return {"sly_data": sly_checks} if sly_checks else {}

    def _find_json_profile(self, agent_name: str, profile_path: Optional[str],
                           project_root: Optional[str]) -> str:
        """Return the path of the JSON profile.

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
        agent_base: str = ProjectPaths.agent_base_name(agent_name)

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
            return candidate

        searched = []

        # Search in the built-in profiles directory next to this module
        profiles_dir = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "profiles",
        )
        for name in (agent_name, agent_base):
            candidate = os.path.join(profiles_dir, f"{name}.json")
            searched.append(candidate)
            if os.path.isfile(candidate):
                return candidate

        # Resolve project root: --project-root flag → PYTHONPATH fallback
        resolved_root: Optional[str] = ProjectPaths.resolve_project_root(project_root)
        if resolved_root:
            for name in (agent_name, agent_base):
                candidate = os.path.normpath(os.path.join(
                    resolved_root, "tests", "load_tests",
                    "prompts", "profiles", f"{name}.json",
                ))
                searched.append(candidate)
                if os.path.isfile(candidate):
                    return candidate

        logger.error(
            "No profile found for agent '%s'.\n"
            "Searched:\n%s\n"
            "Create a profile JSON or use --profile-path to specify one.\n"
            "Aborting.",
            agent_name,
            "".join(f"  - {p}\n" for p in searched),
        )
        raise SystemExit(1)

    def _profile_from_hocons(self, agent_name: str, hocon_files: List[str]) -> Dict[str, Any]:
        """Build the profile dict from test-case hocon files.

        Per file (one prompt each, see _read_load_test_hocon):
          interactions[0].text     -> prompts
          interactions[0].response -> responses (kept as-is; TrafficRunner
              hands each block to the data-driven AgentEvaluators, see
              docs/test_case_hocon_reference.md)
        Agent-wide, may appear in any file and are merged across files:
          failure_patterns             -> union, in first-seen order
          estimated_tokens_per_request -> max

        Aborts when no text is found in any file.
        """
        prompts: List[str] = []
        responses: List[Dict[str, Any]] = []
        failure_patterns: List[str] = []
        estimated_tokens: Optional[int] = None
        for path in hocon_files:
            test_case: Dict[str, Any] = self._read_load_test_hocon(agent_name, path)
            interaction: Dict[str, Any] = next(iter(test_case.get("interactions", [])), {})
            text: Optional[str] = interaction.get("text")
            response: Dict[str, Any] = interaction.get("response", {})
            if text:
                prompts.append(text)
                responses.append(response)
            self._warn_empty_checks(path, response)
            self._extend_unique(failure_patterns, test_case.get("failure_patterns", []))
            tokens: Optional[int] = test_case.get("estimated_tokens_per_request")
            if tokens is not None:
                estimated_tokens = max(tokens, estimated_tokens or 0)

        if not prompts:
            logger.error(
                "No interactions[0].text found in %d hocon file(s) for "
                "agent '%s'.\nAborting.",
                len(hocon_files), agent_name,
            )
            raise SystemExit(1)
        logger.info(
            "Loaded %d prompt(s) from %d hocon file(s) for agent '%s' "
            "(response checks in %d, failure_patterns=%d)",
            len(prompts), len(hocon_files), agent_name,
            sum(1 for response in responses if response), len(failure_patterns),
        )
        data: Dict[str, Any] = {
            "prompts": prompts,
            "responses": responses,
            "failure_patterns": failure_patterns,
        }
        if estimated_tokens is not None:
            data["estimated_tokens_per_request"] = estimated_tokens
        return data

    def _read_load_test_hocon(self, agent_name: str, path: str) -> Dict[str, Any]:
        """Parse and validate one load-test hocon; return its test-case dict.

        A load-test hocon must hold exactly one interaction: the load test
        fires each prompt as an independent single-turn request, so a
        multi-turn conversation cannot be replayed here.
        Its "agent" must match agent_name (or its base name), and
        response and response.sly_data, if present, must be maps as in
        docs/test_case_hocon_reference.md (a bare list is a common mistake).
        Aborts on any of these.
        """
        test_case: Dict[str, Any] = TestsUtil.parse_hocon_test_case(None, path)
        hocon_agent: str = test_case.get("agent", "")
        if hocon_agent not in (agent_name, ProjectPaths.agent_base_name(agent_name)):
            logger.error(
                "Hocon agent does not match --agent.\n"
                "  File: %s\n"
                "  Hocon agent: %s\n"
                "  --agent: %s\nAborting.",
                path, hocon_agent, agent_name,
            )
            raise SystemExit(1)
        interactions: List[Dict[str, Any]] = test_case.get("interactions", [])
        if len(interactions) > 1:
            logger.error(
                "Load-test hocon must have exactly one interaction.\n"
                "  File: %s\n"
                "  Interactions: %d\nAborting.",
                path, len(interactions),
            )
            raise SystemExit(1)
        interaction: Dict[str, Any] = interactions[0] if interactions else {}
        response: Any = interaction.get("response", {})
        sly_checks: Any = response.get("sly_data", {}) if isinstance(response, dict) else None
        if not isinstance(sly_checks, dict):
            logger.error(
                "response and response.sly_data must be maps of field -> check "
                "(see docs/test_case_hocon_reference.md).\n"
                "  File: %s\n"
                "  Got: %r\nAborting.",
                path, sly_checks if isinstance(response, dict) else response,
            )
            raise SystemExit(1)
        return test_case

    def _warn_empty_checks(self, path: str, response: Dict[str, Any]) -> None:
        """Warn about response.sly_data keys with an empty check body.

        The data-driven framework treats `"key": {}` as "no test", so
        such a key is never evaluated; presence is spelled
        `"key": { "not_value": "" }`.
        """
        for key, check in response.get("sly_data", {}).items():
            if check == {}:
                logger.warning(
                    "%s: response.sly_data.%s is {} and will not be checked; "
                    "use { \"not_value\": \"\" } to require a non-empty value",
                    path, key,
                )

    @staticmethod
    def _extend_unique(target: List[str], items: List[str]) -> None:
        """Append items not already in target, preserving order."""
        for item in items:
            if item not in target:
                target.append(item)

    def _read_json(self, path: str) -> Dict[str, Any]:
        """Read profile data from a JSON file via leaf-common persistence."""
        try:
            data: Dict[str, Any] = EasyJsonPersistence(full_ref=path, must_exist=True).restore()
            return data
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Failed to load profile %s: %s\nAborting.", path, exc)
            raise SystemExit(1) from exc
