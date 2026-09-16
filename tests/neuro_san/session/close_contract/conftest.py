
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
Pytest configuration for the agent-session close()/is_closed() contract tests
in this directory (test_http_service_agent_session_close.py and
test_async_http_service_agent_session_close.py).

Why this file exists -- and why it must be named "conftest.py":
    pytest discovers configuration by the exact filename "conftest.py" and
    applies it automatically to every test in this directory and below. It is
    never imported explicitly, so it cannot be renamed to something more
    descriptive without silently disabling everything in it. The directory name
    "close_contract" is what conveys the intent; this file only carries the one
    fixture override those tests need.

What it does:
    The project-wide tests/conftest.py defines an autouse fixture
    `configure_llm_provider_keys` that SKIPS any test which has no OPENAI_API_KEY
    (or other provider key) set. The tests in this directory only exercise the
    client-side close()/is_closed() contract of the HTTP agent sessions -- the
    closed-session guard raises before any request is issued -- so they never
    contact an LLM and must not be skipped when no key is present. This file
    overrides that autouse fixture with a no-op, but ONLY for this directory, so
    the sibling session tests (which do rely on the project-wide behavior) are
    left untouched.
"""
import pytest


# pylint: disable=unused-argument
@pytest.fixture(autouse=True)
def configure_llm_provider_keys(request, monkeypatch):
    """
    No-op override of the project-wide `configure_llm_provider_keys` autouse
    fixture (tests/conftest.py). Same name + autouse => it replaces the
    project-wide one for tests in this directory, so they run without needing an
    LLM provider key. The `request` / `monkeypatch` parameters mirror the
    overridden fixture's signature and are intentionally unused here.
    """
    yield
