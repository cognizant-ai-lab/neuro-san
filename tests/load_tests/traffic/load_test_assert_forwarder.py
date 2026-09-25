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
"""AssertForwarder for the load tester: raises plain AssertionErrors."""

from typing import Any

from neuro_san.test.interfaces.assert_forwarder import AssertForwarder


class LoadTestAssertForwarder(AssertForwarder):
    """AssertForwarder that raises AssertionError without a unittest.TestCase.

    The data-driven AgentEvaluators report through the AssertForwarder
    interface. The load tester is not a unit test, so this implementation
    raises a plain AssertionError with a short, unittest-style message;
    wrap it in an AssertCapture to collect the failures instead.
    """

    @staticmethod
    def _check(condition: bool, default_msg: str, msg: str = None) -> None:
        """Raise AssertionError(msg or default_msg) when condition is false."""
        if not condition:
            raise AssertionError(msg if msg is not None else default_msg)

    # pylint: disable=invalid-name
    def assertEqual(self, first: Any, second: Any, msg: str = None):
        """Assert that the first is equal to the second"""
        self._check(first == second, f"{first!r} != {second!r}", msg)

    def assertNotEqual(self, first: Any, second: Any, msg: str = None):
        """Assert that the first is not equal to the second"""
        self._check(first != second, f"{first!r} == {second!r}", msg)

    def assertTrue(self, expr: Any, msg: str = None):
        """Assert that the expression is true"""
        self._check(bool(expr), f"{expr!r} is not true", msg)

    def assertFalse(self, expr: Any, msg: str = None):
        """Assert that the expression is false"""
        self._check(not expr, f"{expr!r} is not false", msg)

    def assertIs(self, first: Any, second: Any, msg: str = None):
        """Assert that the first and second are the same object"""
        self._check(first is second, f"{first!r} is not {second!r}", msg)

    def assertIsNot(self, first: Any, second: Any, msg: str = None):
        """Assert that the first and second are not the same object"""
        self._check(first is not second,
                    f"unexpectedly identical: {first!r}", msg)

    def assertIsNone(self, expr: Any, msg: str = None):
        """Assert that the expression is None"""
        self._check(expr is None, f"{expr!r} is not None", msg)

    def assertIsNotNone(self, expr: Any, msg: str = None):
        """Assert that the expression is not None"""
        self._check(expr is not None, "unexpectedly None", msg)

    def assertIn(self, member: Any, container: Any, msg: str = None):
        """Assert that the member is in the container"""
        self.assertIsNotNone(container, msg)
        self._check(member in container,
                    f"{member!r} not found in {container!r}", msg)

    def assertNotIn(self, member: Any, container: Any, msg: str = None):
        """Assert that the member is not in the container"""
        self.assertIsNotNone(container, msg)
        self._check(member not in container,
                    f"{member!r} unexpectedly found in {container!r}", msg)

    def assertIsInstance(self, obj: Any, cls: Any, msg: str = None):
        """Assert that the obj is an instance of the cls"""
        self._check(isinstance(obj, cls),
                    f"{obj!r} is not an instance of {cls!r}", msg)

    def assertNotIsInstance(self, obj: Any, cls: Any, msg: str = None):
        """Assert that the obj is not an instance of the cls"""
        self._check(not isinstance(obj, cls),
                    f"{obj!r} is an instance of {cls!r}", msg)

    def assertGreater(self, first: Any, second: Any, msg: str = None):
        """Assert that the first is greater than the second."""
        self._check(first > second,
                    f"{first!r} not greater than {second!r}", msg)

    def assertGreaterEqual(self, first: Any, second: Any, msg: str = None):
        """Assert that the first is greater than or equal to the second."""
        self._check(first >= second,
                    f"{first!r} not greater than or equal to {second!r}", msg)

    def assertLess(self, first: Any, second: Any, msg: str = None):
        """Assert that the first is less than the second."""
        self._check(first < second, f"{first!r} not less than {second!r}", msg)

    def assertLessEqual(self, first: Any, second: Any, msg: str = None):
        """Assert that the first is less than or equal to the second."""
        self._check(first <= second,
                    f"{first!r} not less than or equal to {second!r}", msg)

    def assertGist(self, gist: bool, acceptance_criteria: str,
                   text_sample: str, msg: str = None):
        """Assert that the gist is true"""
        self._check(
            gist,
            f"text_sample did not match acceptance criteria: "
            f"{acceptance_criteria!r}",
            msg,
        )

    def assertNotGist(self, gist: bool, acceptance_criteria: str,
                      text_sample: str, msg: str = None):
        """Assert that the gist is false"""
        self._check(
            not gist,
            f"text_sample unexpectedly matched acceptance criteria: "
            f"{acceptance_criteria!r}",
            msg,
        )
