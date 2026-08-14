
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
"""
Canary module deliberately OUTSIDE any AGENT_TOOL_PATH used in tests.
Resolution tests reference it fully-qualified to prove that default-mode
(Phase 1) resolution imports modules from anywhere on the PYTHONPATH.
Nothing else may import this module.
"""

# Module-level code runs on import; tests use module presence in sys.modules
# to detect whether resolution imported this module.
IMPORTED: bool = True


class CanaryTool:
    """A fixture class resolvable only by fully-qualified (Phase 1) import."""
