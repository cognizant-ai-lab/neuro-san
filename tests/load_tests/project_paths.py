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

"""Path helpers shared by the load test framework."""

import os
from typing import Optional


class ProjectPaths:
    """Resolves locations relative to the neuro-san project root.

    Used by both the profile loader (JSON profiles) and the input
    validator (hocon fixtures) so the lookup rules live in one place.
    """

    @staticmethod
    def resolve_project_root(project_root: Optional[str] = None) -> Optional[str]:
        """Resolve the project root directory.

        Priority: explicit --project-root -> first entry in PYTHONPATH.
        Returns None when neither yields an existing directory.
        """
        if project_root:
            return os.path.abspath(project_root)

        python_path = os.environ.get("PYTHONPATH")
        if python_path:
            first_entry = python_path.split(os.pathsep)[0]
            if os.path.isdir(first_entry):
                return os.path.abspath(first_entry)

        return None

    @staticmethod
    def agent_base_name(agent_name: str) -> str:
        """Strip any registry prefix from an agent name.

        basic/hello_world -> hello_world. Profile files and fixture
        folders are keyed by this base name.
        """
        return agent_name.rsplit("/", 1)[-1]
