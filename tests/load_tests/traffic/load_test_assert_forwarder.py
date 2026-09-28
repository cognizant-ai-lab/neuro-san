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
AssertForwarder for the load tester: raises plain AssertionErrors.
"""

from typing import Any
from typing import Optional

from typing_extensions import override

from neuro_san.test.interfaces.assert_forwarder import AssertForwarder


class LoadTestAssertForwarder(AssertForwarder):
    """
    AssertForwarder that raises AssertionError without a unittest.TestCase.

    The data-driven AgentEvaluators report through the AssertForwarder
    interface. The load tester is not a unit test, so this implementation
    raises a plain AssertionError with a short, unittest-style message;
    wrap it in an AssertCapture to collect the failures instead.
    Every assert* method is an override of AssertForwarder; _check is ours.
    """

    @staticmethod
    def _check(condition: bool, default_msg: str, msg: Optional[str] = None) -> None:
        """
        Raise AssertionError when condition is false.

        :param condition: The result of the assertion
        :param default_msg: Message to use when the caller gave none
        :param msg: Optional caller-supplied message
        :raises AssertionError: When condition is false
        """
        if not condition:
            raise AssertionError(msg if msg is not None else default_msg)

    # pylint: disable=invalid-name
    @override
    def assertEqual(self, first: Any, second: Any, msg: str = None) -> None:
        """
        Assert that the first is equal to the second

        :param first: First comparison element
        :param second: Second comparison element
        :param msg: optional string message
        """
        self._check(first == second, f"{first!r} != {second!r}", msg)

    @override
    def assertNotEqual(self, first: Any, second: Any, msg: str = None) -> None:
        """
        Assert that the first is not equal to the second

        :param first: First comparison element
        :param second: Second comparison element
        :param msg: optional string message
        """
        self._check(first != second, f"{first!r} == {second!r}", msg)

    @override
    def assertTrue(self, expr: Any, msg: str = None) -> None:
        """
        Assert that the expression is true

        :param expr: Expression to test
        :param msg: optional string message
        """
        self._check(bool(expr), f"{expr!r} is not true", msg)

    @override
    def assertFalse(self, expr: Any, msg: str = None) -> None:
        """
        Assert that the expression is false

        :param expr: Expression to test
        :param msg: optional string message
        """
        self._check(not expr, f"{expr!r} is not false", msg)

    @override
    def assertIs(self, first: Any, second: Any, msg: str = None) -> None:
        """
        Assert that the first and second are the same object

        :param first: First comparison element
        :param second: Second comparison element
        :param msg: optional string message
        """
        self._check(first is second, f"{first!r} is not {second!r}", msg)

    @override
    def assertIsNot(self, first: Any, second: Any, msg: str = None) -> None:
        """
        Assert that the first and second are not the same object

        :param first: First comparison element
        :param second: Second comparison element
        :param msg: optional string message
        """
        self._check(first is not second, f"unexpectedly identical: {first!r}", msg)

    @override
    def assertIsNone(self, expr: Any, msg: str = None) -> None:
        """
        Assert that the expression is None

        :param expr: Expression to test
        :param msg: optional string message
        """
        self._check(expr is None, f"{expr!r} is not None", msg)

    @override
    def assertIsNotNone(self, expr: Any, msg: str = None) -> None:
        """
        Assert that the expression is not None

        :param expr: Expression to test
        :param msg: optional string message
        """
        self._check(expr is not None, "unexpectedly None", msg)

    @override
    def assertIn(self, member: Any, container: Any, msg: str = None) -> None:
        """
        Assert that the member is in the container

        :param member: Member comparison element
        :param container: Container comparison element
        :param msg: optional string message
        """
        self.assertIsNotNone(container, msg)
        self._check(member in container, f"{member!r} not found in {container!r}", msg)

    @override
    def assertNotIn(self, member: Any, container: Any, msg: str = None) -> None:
        """
        Assert that the member is not in the container

        :param member: Member comparison element
        :param container: Container comparison element
        :param msg: optional string message
        """
        self.assertIsNotNone(container, msg)
        self._check(member not in container, f"{member!r} unexpectedly found in {container!r}", msg)

    @override
    def assertIsInstance(self, obj: Any, cls: Any, msg: str = None) -> None:
        """
        Assert that the obj is an instance of the cls

        :param obj: object instance comparison element
        :param cls: Class comparison element
        :param msg: optional string message
        """
        self._check(isinstance(obj, cls), f"{obj!r} is not an instance of {cls!r}", msg)

    @override
    def assertNotIsInstance(self, obj: Any, cls: Any, msg: str = None) -> None:
        """
        Assert that the obj is not an instance of the cls

        :param obj: object instance comparison element
        :param cls: Class comparison element
        :param msg: optional string message
        """
        self._check(not isinstance(obj, cls), f"{obj!r} is an instance of {cls!r}", msg)

    @override
    def assertGreater(self, first: Any, second: Any, msg: str = None) -> None:
        """
        Assert that the first is greater than the second.

        :param first: First comparison element
        :param second: Second comparison element
        :param msg: optional string message
        """
        self._check(first > second, f"{first!r} not greater than {second!r}", msg)

    @override
    def assertGreaterEqual(self, first: Any, second: Any, msg: str = None) -> None:
        """
        Assert that the first is greater than or equal to the second.

        :param first: First comparison element
        :param second: Second comparison element
        :param msg: optional string message
        """
        self._check(first >= second, f"{first!r} not greater than or equal to {second!r}", msg)

    @override
    def assertLess(self, first: Any, second: Any, msg: str = None) -> None:
        """
        Assert that the first is less than the second.

        :param first: First comparison element
        :param second: Second comparison element
        :param msg: optional string message
        """
        self._check(first < second, f"{first!r} not less than {second!r}", msg)

    @override
    def assertLessEqual(self, first: Any, second: Any, msg: str = None) -> None:
        """
        Assert that the first is less than or equal to the second.

        :param first: First comparison element
        :param second: Second comparison element
        :param msg: optional string message
        """
        self._check(first <= second, f"{first!r} not less than or equal to {second!r}", msg)

    @override
    def assertGist(self, gist: bool, acceptance_criteria: str, text_sample: str, msg: str = None) -> None:
        """
        Assert that the gist is true

        :param gist: Pass/Fail value of the gist expected to be True
        :param acceptance_criteria: The value to verify against
        :param text_sample: The value appearing in the test sample
        :param msg: optional string message
        """
        self._check(gist, f"text_sample did not match acceptance criteria: {acceptance_criteria!r}", msg)

    @override
    def assertNotGist(self, gist: bool, acceptance_criteria: str, text_sample: str, msg: str = None) -> None:
        """
        Assert that the gist is false

        :param gist: Pass/Fail value of the gist expected to be False
        :param acceptance_criteria: The value to verify against
        :param text_sample: The value appearing in the test sample
        :param msg: optional string message
        """
        self._check(not gist, f"text_sample unexpectedly matched acceptance criteria: {acceptance_criteria!r}", msg)
