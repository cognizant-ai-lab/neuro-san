
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
from typing import List

from neuro_san.test.interfaces.assert_forwarder import AssertForwarder


class AssertCapture(AssertForwarder):
    """
    AssertForwarder implementation that wraps another AssertForwarder and
    captures any exceptions thrown from it.
    """

    def __init__(self, basis: AssertForwarder):
        """
        Constructor

        :param basis: AssertForwarder
        """
        self.basis: AssertForwarder = basis
        self.asserts: List[AssertionError] = []

    def get_asserts(self) -> List[AssertionError]:
        """
        :return: The list of asserts captured from the basis
        """
        return self.asserts

    def add_assert(self, assertion_error: AssertionError):
        """
        Add an assertion error to the list of captured asserts.

        :param assertion_error: The assertion error to add
        """
        self.asserts.append(assertion_error)

    # pylint: disable=invalid-name
    def assertEqual(self, first: Any, second: Any, msg: str = None):
        """
        Assert that the first is equal to the second

        :param first: First comparison element
        :param second: Second comparison element
        :param msg: optional string message
        """
        try:
            self.basis.assertEqual(first, second, msg)
        except AssertionError as exception:
            self.asserts.append(exception)

    # pylint: disable=invalid-name
    def assertNotEqual(self, first: Any, second: Any, msg: str = None):
        """
        Assert that the first is not equal to the second

        :param first: First comparison element
        :param second: Second comparison element
        :param msg: optional string message
        """
        try:
            self.basis.assertNotEqual(first, second, msg)
        except AssertionError as exception:
            self.asserts.append(exception)

    # pylint: disable=invalid-name
    def assertTrue(self, expr: Any, msg: str = None):
        """
        Assert that the expression is true

        :param expr: Expression to test
        :param msg: optional string message
        """
        try:
            self.basis.assertTrue(expr, msg)
        except AssertionError as exception:
            self.asserts.append(exception)

    # pylint: disable=invalid-name
    def assertFalse(self, expr: Any, msg: str = None):
        """
        Assert that the expression is false

        :param expr: Expression to test
        :param msg: optional string message
        """
        try:
            self.basis.assertFalse(expr, msg)
        except AssertionError as exception:
            self.asserts.append(exception)

    # pylint: disable=invalid-name
    def assertIs(self, first: Any, second: Any, msg: str = None):
        """
        Assert that the first and second are the same object

        :param first: First comparison element
        :param second: Second comparison element
        :param msg: optional string message
        """
        try:
            self.basis.assertIs(first, second, msg)
        except AssertionError as exception:
            self.asserts.append(exception)

    # pylint: disable=invalid-name
    def assertIsNot(self, first: Any, second: Any, msg: str = None):
        """
        Assert that the first and second are not the same object

        :param first: First comparison element
        :param second: Second comparison element
        :param msg: optional string message
        """
        try:
            self.basis.assertIsNot(first, second, msg)
        except AssertionError as exception:
            self.asserts.append(exception)

    # pylint: disable=invalid-name
    def assertIsNone(self, expr: Any, msg: str = None):
        """
        Assert that the expression is None

        :param expr: Expression to test
        :param msg: optional string message
        """
        try:
            self.basis.assertIsNone(expr, msg)
        except AssertionError as exception:
            self.asserts.append(exception)

    # pylint: disable=invalid-name
    def assertIsNotNone(self, expr: Any, msg: str = None):
        """
        Assert that the expression is not None

        :param expr: Expression to test
        :param msg: optional string message
        """
        try:
            self.basis.assertIsNotNone(expr, msg)
        except AssertionError as exception:
            self.asserts.append(exception)

    # pylint: disable=invalid-name
    def assertIn(self, member: Any, container: Any, msg: str = None):
        """
        Assert that the member is in the container

        :param member: Member comparison element
        :param container: Container comparison element
        :param msg: optional string message
        """
        try:
            self.basis.assertIn(member, container, msg)
        except AssertionError as exception:
            self.asserts.append(exception)

    # pylint: disable=invalid-name
    def assertNotIn(self, member: Any, container: Any, msg: str = None):
        """
        Assert that the member is not in the container

        :param member: Member comparison element
        :param container: Container comparison element
        :param msg: optional string message
        """
        try:
            self.basis.assertNotIn(member, container, msg)
        except AssertionError as exception:
            self.asserts.append(exception)

    # pylint: disable=invalid-name
    def assertIsInstance(self, obj: Any, cls: Any, msg: str = None):
        """
        Assert that the obj is an instance of the cls

        :param obj: object instance comparison element
        :param cls: Class comparison element
        :param msg: optional string message
        """
        try:
            self.basis.assertIsInstance(obj, cls, msg)
        except AssertionError as exception:
            self.asserts.append(exception)

    # pylint: disable=invalid-name
    def assertNotIsInstance(self, obj: Any, cls: Any, msg: str = None):
        """
        Assert that the obj is not an instance of the cls

        :param obj: object instance comparison element
        :param cls: Class comparison element
        :param msg: optional string message
        """
        try:
            self.basis.assertNotIsInstance(obj, cls, msg)
        except AssertionError as exception:
            self.asserts.append(exception)

    # pylint: disable=invalid-name
    def assertGreater(self, first: Any, second: Any, msg: str = None):
        """
        Assert that the first is greater than the second.

        :param first: First comparison element
        :param second: Second comparison element
        :param msg: optional string message
        """
        try:
            self.basis.assertGreater(first, second, msg)
        except AssertionError as exception:
            self.asserts.append(exception)

    # pylint: disable=invalid-name
    def assertGreaterEqual(self, first: Any, second: Any, msg: str = None):
        """
        Assert that the first is greater than or equal to the second.

        :param first: First comparison element
        :param second: Second comparison element
        :param msg: optional string message
        """
        try:
            self.basis.assertGreaterEqual(first, second, msg)
        except AssertionError as exception:
            self.asserts.append(exception)

    # pylint: disable=invalid-name
    def assertLess(self, first: Any, second: Any, msg: str = None):
        """
        Assert that the first is less than the second.

        :param first: First comparison element
        :param second: Second comparison element
        :param msg: optional string message
        """
        try:
            self.basis.assertLess(first, second, msg)
        except AssertionError as exception:
            self.asserts.append(exception)

    # pylint: disable=invalid-name
    def assertLessEqual(self, first: Any, second: Any, msg: str = None):
        """
        Assert that the first is less than or equal to the second.

        :param first: First comparison element
        :param second: Second comparison element
        :param msg: optional string message
        """
        try:
            self.basis.assertLessEqual(first, second, msg)
        except AssertionError as exception:
            self.asserts.append(exception)

    # pylint: disable=invalid-name
    def assertGist(self, gist: bool, acceptance_criteria: str, text_sample: str, msg: str = None):
        """
        Assert that the gist is true

        :param gist: Pass/Fail value of the gist expected to be True
        :param acceptance_criteria: The value to verify against
        :param text_sample: The value appearing in the test sample
        :param msg: optional string message
        """
        try:
            self.basis.assertGist(gist, acceptance_criteria, text_sample, msg)
        except AssertionError as exception:
            self.asserts.append(exception)

    # pylint: disable=invalid-name
    def assertNotGist(self, gist: bool, acceptance_criteria: str, text_sample: str, msg: str = None):
        """
        Assert that the gist is true

        :param gist: Pass/Fail value of the gist expected to be False
        :param acceptance_criteria: The value to verify against
        :param text_sample: The value appearing in the test sample
        :param msg: optional string message
        """
        try:
            self.basis.assertNotGist(gist, acceptance_criteria, text_sample, msg)
        except AssertionError as exception:
            self.asserts.append(exception)
