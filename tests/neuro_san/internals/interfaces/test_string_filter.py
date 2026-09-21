
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
from unittest import TestCase

from neuro_san.internals.interfaces.string_filter import StringFilter


class TestStringFilter(TestCase):
    """
    Unit tests for the StringFilter interface.
    """

    def test_filter_is_abstract(self) -> None:
        """
        The interface itself does not filter anything; implementations must override filter().
        """
        with self.assertRaises(NotImplementedError):
            StringFilter().filter("anything")
