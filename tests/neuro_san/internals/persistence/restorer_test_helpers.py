
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
Helpers shared by the restorer test files in this directory.
"""
from typing import Any
from typing import Dict

from pathlib import Path

from neuro_san.internals.persistence.abstract_async_config_restorer import AbstractAsyncConfigRestorer


class ConcreteRestorer(AbstractAsyncConfigRestorer):
    """Minimal concrete subclass – inherits all behaviour from the abstract base."""


# The dictionary the valid.json and valid.hocon fixture files deserialize to.
VALID_DICT: Dict[str, Any] = {"key": "value", "nested": {"a": 1}}

# Directory containing .json and .hocon fixture files used by the tests.
FIXTURES_DIR: Path = Path(__file__).parent.parent.parent.parent / "fixtures"
