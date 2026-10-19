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

import logging
import os
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Set

from leaf_common.persistence.easy.easy_json_persistence import EasyJsonPersistence

from neuro_san.test.util.tests_util import TestsUtil
from tests.load_tests.project_paths import ProjectPaths
from tests.load_tests.prompts.agent_profile import AgentProfile
from tests.load_tests.validation.load_test_abort_error import LoadTestAbortError

logger: logging.Logger = logging.getLogger(__name__)


class AgentProfileFactory:
    """
    Builds AgentProfile instances.

    Policy lives here (where the profile comes from, how hocons map to
    profile settings, validation); AgentProfile itself only carries data.
    """

    def create(self, agent_name: str, profile_path: Optional[str] = None,
               project_root: Optional[str] = None,
               hocon_files: Optional[List[str]] = None) -> AgentProfile:
        """
        Create an AgentProfile.

        When hocon_files is given, the whole profile is built from those
        test-case hocons and no JSON profile is read; see
        _profile_from_hocons() for the hocon keys used.
        Otherwise the profile comes from a JSON file; see
        _find_json_profile() for the search order.

        :param agent_name: --agent value, e.g. basic/hello_world
        :param profile_path: --profile-path directory, or None
        :param project_root: --project-root value, or None to use PYTHONPATH
        :param hocon_files: Test-case hocon files; when given, no JSON profile is read
        :return: The agent's profile
        :raises LoadTestAbortError: With exit code 1 when the profile cannot be read or is not valid
        """
        if hocon_files:
            return AgentProfile(agent_name, self._profile_from_hocons(agent_name, hocon_files))
        path: str = self._find_json_profile(agent_name, profile_path, project_root)
        logger.info("Loaded agent profile: %s", path)
        data: Optional[Dict[str, Any]] = EasyJsonPersistence(full_ref=path, must_exist=True).restore()
        if data is None:
            # EasyJsonPersistence returns None when the JSON is a list or a single value.
            logger.error(
                """Agent profile must be a JSON object ({...}), not a list or a single value.
  File: %s
Aborting.""",
                path,
            )
            raise LoadTestAbortError(1)
        data["responses"] = [self._response_from_success_fields(data.get("success_fields", []))]
        return AgentProfile(agent_name, data)

    def _response_from_success_fields(self, success_fields: List[str]) -> Dict[str, Any]:
        """
        Express a JSON profile's success_fields as a hocon-style response block.

        Each field becomes sly_data.<field>: { not_value: "" }, i.e. the
        ValueAgentEvaluator requires it to be present and non-empty. The
        field is a DictionaryExtractor path from the top of sly_data.
        DictionaryExtractor does not index into lists, so a value nested
        in a list (agent_reservations[0].reservation_id) can only be named
        by its top-level key (agent_reservations): the check then passes
        for any non-empty list, even one whose reservation_id is empty.

        :param success_fields: sly_data keys the JSON profile requires
        :return: A response block with one not_value check per field,
                 or {} when there are no fields
        """
        sly_checks: Dict[str, Any] = {}
        field: str
        # Add a not_value check for each required sly_data field
        for field in success_fields:
            sly_checks[field] = {"not_value": ""}
        if not sly_checks:
            return {}
        return {"sly_data": sly_checks}

    def _find_json_profile(self, agent_name: str, profile_path: Optional[str], project_root: Optional[str]) -> str:
        """
        Return the path of the JSON profile.

        Search order:
        1. --profile-path directory: look for {base}.json there
        2. ./profiles/{agent_name}.json then ./profiles/{base}.json
        3. {project_root}/tests/load_tests/prompts/profiles/{name}.json
           where project_root comes from --project-root or PYTHONPATH
        4. Not found → LoadTestAbortError

        When agent_name includes a prefix (e.g. basic/hello_world),
        the base name (hello_world) is tried as a fallback so
        --profile-path is not required for prefixed agents.

        :param agent_name: --agent value, e.g. basic/hello_world
        :param profile_path: --profile-path directory, or None
        :param project_root: --project-root value, or None to use PYTHONPATH
        :return: Path of the JSON profile file
        :raises LoadTestAbortError: With exit code 1 when --profile-path is a file or no profile is found
        """
        agent_base: str = ProjectPaths.agent_base_name(agent_name)

        candidate: str = ""
        if profile_path:
            if os.path.isfile(profile_path):
                logger.error(
                    """--profile-path should be a directory, not a file.
  Got: %s
  Try: --profile-path %s""",
                    profile_path, os.path.dirname(profile_path),
                )
                raise LoadTestAbortError(1)
            candidate = os.path.join(profile_path, f"{agent_base}.json")
            if not os.path.isfile(candidate):
                logger.error(
                    """Profile not found: %s
  --profile-path directory: %s
  Expected file: %s.json
  Aborting.""",
                    candidate, profile_path, agent_base,
                )
                raise LoadTestAbortError(1)
            return candidate

        searched: List[str] = []

        # Search in the built-in profiles directory next to this module
        profiles_dir: str = os.path.join(os.path.dirname(os.path.abspath(__file__)), "profiles")
        profile_names: List[str] = [agent_name, agent_base]
        name: str
        # Check the full agent name, then its base name
        for name in profile_names:
            candidate = os.path.join(profiles_dir, f"{name}.json")
            searched.append(candidate)
            if os.path.isfile(candidate):
                return candidate

        # Resolve project root: --project-root flag → PYTHONPATH fallback
        resolved_root: Optional[str] = ProjectPaths.resolve_project_root(project_root)
        if resolved_root:
            # Check the full agent name, then its base name, under the project root
            for name in profile_names:
                candidate = os.path.normpath(os.path.join(
                    resolved_root, "tests", "load_tests",
                    "prompts", "profiles", f"{name}.json",
                ))
                searched.append(candidate)
                if os.path.isfile(candidate):
                    return candidate

        searched_lines: List[str] = []
        searched_path: str
        # One "  - <path>" line per searched path.
        for searched_path in searched:
            searched_lines.append(f"  - {searched_path}\n")
        logger.error(
            """No profile found for agent '%s'.
Searched:
%s
Create a profile JSON or use --profile-path to specify one.
Aborting.""",
            agent_name,
            "".join(searched_lines),
        )
        raise LoadTestAbortError(1)

    def _profile_from_hocons(self, agent_name: str, hocon_files: List[str]) -> Dict[str, Any]:
        """
        Build the profile dict from test-case hocon files.

        Per file (one prompt each, see _read_load_test_hocon):
          interactions[0].text     -> prompts
          interactions[0].response -> responses (kept as-is; TrafficRunner
              hands each block to the data-driven AgentEvaluators, see
              docs/test_case_hocon_reference.md)
        Agent-wide, may appear in any file and are merged across files:
          failure_patterns             -> union, sorted
          estimated_tokens_per_request -> max

        :param agent_name: --agent value, checked against each hocon's agent
        :param hocon_files: Test-case hocon files, one prompt each
        :return: Profile data with prompts, responses, failure_patterns and, when set, estimated_tokens_per_request
        :raises LoadTestAbortError: With exit code 1 when no file has interactions[0].text, or a file is not valid
        """
        prompts: List[str] = []
        responses: List[Dict[str, Any]] = []
        failure_patterns: Set[str] = set()
        estimated_tokens: Optional[int] = None
        path: str
        # Collect the prompt, response checks and failure patterns from each hocon file
        for path in hocon_files:
            test_case: Dict[str, Any] = self._read_load_test_hocon(agent_name, path)
            interaction: Dict[str, Any] = next(iter(test_case.get("interactions", [])), {})
            text: Optional[str] = interaction.get("text")
            response: Dict[str, Any] = interaction.get("response", {})
            if text:
                prompts.append(text)
                responses.append(response)
            self._warn_empty_checks(path, response)
            failure_patterns.update(test_case.get("failure_patterns", []))
            tokens: Optional[int] = test_case.get("estimated_tokens_per_request")
            if tokens is not None:
                estimated_tokens = max(tokens, estimated_tokens or 0)

        if not prompts:
            logger.error(
                "No interactions[0].text found in %d hocon file(s) for agent '%s'.\nAborting.",
                len(hocon_files), agent_name,
            )
            raise LoadTestAbortError(1)
        checked: int = 0
        # Count the prompts that have response checks
        for response in responses:
            if response:
                checked += 1
        logger.info(
            "Loaded %d prompt(s) from %d hocon file(s) for agent '%s' (response checks in %d, failure_patterns=%d)",
            len(prompts), len(hocon_files), agent_name,
            checked, len(failure_patterns),
        )
        data: Dict[str, Any] = {
            "prompts": prompts,
            "responses": responses,
            "failure_patterns": sorted(failure_patterns),
        }
        if estimated_tokens is not None:
            data["estimated_tokens_per_request"] = estimated_tokens
        return data

    def _read_load_test_hocon(self, agent_name: str, path: str) -> Dict[str, Any]:
        """
        Parse and validate one load-test hocon; return its test-case dict.

        A load-test hocon must hold exactly one interaction: the load test
        fires each prompt as an independent single-turn request, so a
        multi-turn conversation cannot be replayed here.
        Its "agent" must match agent_name (or its base name), and
        response and response.sly_data, if present, must be maps as in
        docs/test_case_hocon_reference.md (a bare list is a common mistake).

        :param agent_name: --agent value; the hocon's agent must match it or its base name
        :param path: Path to the hocon file
        :return: The parsed test case
        :raises LoadTestAbortError: With exit code 1 when any of these checks fails
        """
        test_case: Dict[str, Any] = TestsUtil.parse_hocon_test_case(None, path)
        hocon_agent: str = test_case.get("agent", "")
        expected_agents: List[str] = [agent_name, ProjectPaths.agent_base_name(agent_name)]
        if hocon_agent not in expected_agents:
            logger.error(
                """Hocon agent does not match --agent.
  File: %s
  Hocon agent: %s
  --agent: %s
Aborting.""",
                path, hocon_agent, agent_name,
            )
            raise LoadTestAbortError(1)
        interactions: List[Dict[str, Any]] = test_case.get("interactions", [])
        interaction_count: int = len(interactions)
        if interaction_count > 1:
            logger.error(
                """Load-test hocon must have exactly one interaction.
  File: %s
  Interactions: %d
Aborting.""",
                path, interaction_count,
            )
            raise LoadTestAbortError(1)
        interaction: Dict[str, Any] = {}
        if interactions:
            interaction = interactions[0]
        response: Any = interaction.get("response", {})
        sly_checks: Any = None
        bad_value: Any = response
        if isinstance(response, dict):
            response_dict: Dict[str, Any] = response
            sly_checks = response_dict.get("sly_data", {})
            bad_value = sly_checks
        if not isinstance(sly_checks, dict):
            logger.error(
                """response and response.sly_data must be maps of field -> check \
(see docs/test_case_hocon_reference.md).
  File: %s
  Got: %r
Aborting.""",
                path, bad_value,
            )
            raise LoadTestAbortError(1)
        return test_case

    def _warn_empty_checks(self, path: str, response: Dict[str, Any]) -> None:
        """
        Warn about response.sly_data keys with an empty check body.

        The data-driven framework treats `"key": {}` as "no test", so
        such a key is never evaluated; presence is spelled
        `"key": { "not_value": "" }`.

        :param path: The hocon file the response block came from, for the message
        :param response: The interaction's response block
        """
        key: str
        check: Any
        # Find the sly_data keys whose check body is empty
        for key, check in response.get("sly_data", {}).items():
            if check == {}:
                logger.warning(
                    "%s: response.sly_data.%s is {} and will not be checked; "
                    "use { \"not_value\": \"\" } to require a non-empty value",
                    path, key,
                )
