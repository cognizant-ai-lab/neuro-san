
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

Resolution tests reference it fully-qualified two ways:
- default mode resolves it (proving Phase 1 imports from anywhere on PYTHONPATH);
- strict mode must NOT import it (importing executes top-level code, which is
  the vulnerability the flag closes), asserted via absence from sys.modules.

Nothing else may import this module, or the strict test's never-imported
assertion loses its meaning.
"""


class CanaryTool:
    """A fixture class resolvable only by fully-qualified (Phase 1) import."""
