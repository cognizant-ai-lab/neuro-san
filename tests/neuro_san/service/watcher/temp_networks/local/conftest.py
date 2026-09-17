
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
Scoped conftest for the LocalReservationsStorage tests.

The project-wide tests/conftest.py declares an autouse fixture
`configure_llm_provider_keys` that skips any test missing an
OPENAI_API_KEY (or other provider key, depending on markers). Tests in
this directory exercise in-memory and on-disk reservation storage plus the
network config filter chain and never call an LLM provider, so the
project-wide skip condition does not apply. This conftest overrides that
fixture with a no-op for tests in this subtree only, mirroring
tests/neuro_san/service/watcher/temp_networks/s3/conftest.py.
"""
import pytest


# pylint: disable=unused-argument
@pytest.fixture(autouse=True)
def configure_llm_provider_keys(request, monkeypatch):
    """
    Override of the project-wide configure_llm_provider_keys fixture.
    Reservation-storage tests never call an LLM and therefore should not
    be skipped when no provider key is set.
    """
    return None
