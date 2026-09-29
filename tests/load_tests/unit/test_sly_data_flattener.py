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


from typing import Any
from typing import Dict
from unittest import TestCase

from tests.load_tests.reporting.sly_data_flattener import SlyDataFlattener


class TestSlyDataFlattener(TestCase):
    """Tests for SlyDataFlattener."""

    def test_nested_string_fields_are_found(self) -> None:
        """Strings at the top level, inside dicts and inside lists are all collected."""
        sly_data: Dict[str, Any] = {
            "top": "a",
            "nested": {"inner": "b", "count": 3},
            "agent_reservations": [{"reservation_id": "abc-1"}, ["ignored", {"deep": "c"}]],
        }
        self.assertEqual(
            SlyDataFlattener.flatten_string_fields(sly_data),
            {"top": "a", "inner": "b", "reservation_id": "abc-1", "deep": "c"},
        )

    def test_first_occurrence_wins(self) -> None:
        """A name seen twice keeps its first value."""
        sly_data: Dict[str, Any] = {"id": "first", "child": {"id": "second"}}
        self.assertEqual(SlyDataFlattener.flatten_string_fields(sly_data), {"id": "first"})

    def test_empty(self) -> None:
        """No sly_data gives no fields."""
        self.assertEqual(SlyDataFlattener.flatten_string_fields({}), {})
