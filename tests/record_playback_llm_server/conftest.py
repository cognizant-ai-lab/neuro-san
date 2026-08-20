
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
Local pytest configuration for the record/playback proxy tests.
"""
import pytest


@pytest.fixture(autouse=True)
def configure_llm_provider_keys():
    """
    Override the repo-wide autouse fixture of the same name (tests/conftest.py),
    which skips tests when no LLM provider API key is present. These proxy tests
    drive a local in-process fake upstream and never contact a real LLM, so no
    provider key is required.
    """
    yield
