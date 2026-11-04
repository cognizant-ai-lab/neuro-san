
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
import os
from typing import List
from typing import Set

import pytest

# Markers of the integration, smoke and non-default-provider suites, which run selectively.
# Tests carrying none of these never have their provider keys checked, so a basic unit test
# that needs a missing key fails rather than being skipped.
LLM_MARKERS: List[str] = ["integration", "smoke", "non_default_llm_provider"]


@pytest.fixture(autouse=True)
def configure_llm_provider_keys(request, monkeypatch):
    """
    Ensure only the appropriate LLM provider keys are available for a test marked as using an LLM.
    Tests without any of the LLM_MARKERS are left alone.
    """

    marker_names: Set[str] = set()
    marker: pytest.Mark
    # Collect the names of all markers on the test, its class and its module
    for marker in request.node.iter_markers():
        marker_names.add(marker.name)
    if marker_names.isdisjoint(LLM_MARKERS):
        return

    is_non_default = request.node.get_closest_marker("non_default_llm_provider")
    is_anthropic = request.node.get_closest_marker("anthropic")
    is_azure = request.node.get_closest_marker("azure")
    is_gemini = request.node.get_closest_marker("gemini")
    is_ollama = request.node.get_closest_marker("ollama")

    if is_non_default:
        # For any non-default provider: clear OPENAI key to prevent accidental use
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        if is_anthropic:
            if not os.getenv("ANTHROPIC_API_KEY"):
                pytest.skip("Missing ANTHROPIC_API_KEY for test marked 'anthropic'")
        elif is_azure:
            if not os.getenv("AZURE_OPENAI_API_KEY"):
                pytest.skip("Missing AZURE_OPENAI_API_KEY for test marked 'azure'")
        elif is_gemini:
            if not os.getenv("GOOGLE_API_KEY"):
                pytest.skip("Missing GOOGLE_API_KEY for test marked 'gemini'")
        elif is_ollama:
            print("No key needed for test marked 'ollama'")
        else:
            pytest.skip("Unknown non-default provider; test requires explicit key handling.")
    else:
        # Default case: assume OpenAI is used
        if not os.getenv("OPENAI_API_KEY"):
            pytest.skip("Missing OPENAI_API_KEY for default LLM test.")
