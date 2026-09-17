
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
Pytest configuration for the data-driven test-driver unit tests in this directory.

Must be named "conftest.py": pytest auto-discovers it by that exact name and
applies it to this directory only. These tests exercise SessionCanceller with
in-memory mock sessions and never contact an LLM, so the project-wide
`configure_llm_provider_keys` autouse fixture (tests/conftest.py), which skips
tests lacking an OPENAI_API_KEY, is overridden here with a no-op -- leaving other
tests unaffected.
"""
import pytest


# pylint: disable=unused-argument
@pytest.fixture(autouse=True)
def configure_llm_provider_keys(request, monkeypatch):
    """No-op override of the project-wide provider-key fixture for these tests."""
    yield
