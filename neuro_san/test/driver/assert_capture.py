
# Copyright (C) 2023-2025 Cognizant Digital Business, Evolutionary AI.
# All Rights Reserved.
# Issued under the Academic Public License.
#
# You can be released from the terms, and requirements of the Academic Public
# License by purchasing a commercial license.
# Purchase of a commercial license is mandatory for any use of the
# neuro-san SDK Software in commercial settings.
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
