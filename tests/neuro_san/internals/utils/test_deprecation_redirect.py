
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
from typing import Type

from unittest import TestCase

from neuro_san.internals.utils.deprecation_redirect import DeprecationRedirect


class TestDeprecationRedirect(TestCase):
    """
    Tests for the DeprecationRedirect class.
    """

    def test_constructor(self):
        """
        Can we construct a DeprecationRedirect?
        """
        redirect = DeprecationRedirect("foo", {})
        self.assertIsNotNone(redirect)

    def test_redirect_modules(self):
        """
        Can we redirect deprecated modules?
        """
        redirect = DeprecationRedirect(
            "neuro_san",
            {
                "neuro_san.bogus.batty.Batty": "neuro_san.interfaces.coded_tool.CodedTool"
            }
        )

        new_class: Type[Any] = redirect.redirect_class("Batty")

        self.assertIsNotNone(new_class)

        fully_qualified: str = f"{new_class.__module__}.{new_class.__qualname__}"
        self.assertEqual("neuro_san.interfaces.coded_tool.CodedTool", fully_qualified)
