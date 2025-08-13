
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

from unittest import TestCase

from neuro_san.test.interfaces.assert_forwarder import AssertForwarder


class UnitTestAssertForwarder(AssertForwarder):
    """
    AssertForwarder implemetation for python unittest.TestCase
    """

    def __init__(self, test_case: TestCase):
        """
        Constructor

        :param test_case: The python unitest.TestCase instance on which to base any asserts.
        """
        self.test_case: TestCase = test_case

    def assertEqual(self, first: Any, second: Any, msg: str = None):
        """
        Assert that the first is equal to the second

        :param first: First comparison element
        :param second: Second comparison element
        :param msg: optional string message
        """
        self.test_case.assertEqual(first, second, msg=msg)

    def assertNotEqual(self, first: Any, second: Any, msg: str = None):
        """
        Assert that the first is not equal to the second

        :param first: First comparison element
        :param second: Second comparison element
        :param msg: optional string message
        """
        self.test_case.assertNotEqual(first, second, msg=msg)

    def assertTrue(self, expr: Any, msg: str = None):
        """
        Assert that the expression is true

        :param expr: Expression to test
        :param msg: optional string message
        """
        self.test_case.assertTrue(expr, msg=msg)

    def assertFalse(self, expr: Any, msg: str = None):
        """
        Assert that the expression is false

        :param expr: Expression to test
        :param msg: optional string message
        """
        self.test_case.assertFalse(expr, msg=msg)

    def assertIs(self, first: Any, second: Any, msg: str = None):
        """
        Assert that the first and second are the same object

        :param first: First comparison element
        :param second: Second comparison element
        :param msg: optional string message
        """
        self.test_case.assertIs(first, second, msg=msg)

    def assertIsNot(self, first: Any, second: Any, msg: str = None):
        """
        Assert that the first and second are not the same object

        :param first: First comparison element
        :param second: Second comparison element
        :param msg: optional string message
        """
        self.test_case.assertIsNot(first, second, msg=msg)

    def assertIsNone(self, expr: Any, msg: str = None):
        """
        Assert that the expression is None

        :param expr: Expression to test
        :param msg: optional string message
        """
        self.test_case.assertIsNone(expr, msg=msg)

    def assertIsNotNone(self, expr: Any, msg: str = None):
        """
        Assert that the expression is not None

        :param expr: Expression to test
        :param msg: optional string message
        """
        self.test_case.assertIsNotNone(expr, msg=msg)

    def assertIn(self, member: Any, container: Any, msg: str = None):
        """
        Assert that the member is in the container

        :param member: Member comparison element
        :param container: Container comparison element
        :param msg: optional string message
        """
        self.assertIsNotNone(container, msg=msg)
        self.test_case.assertIn(member, container, msg=msg)

    def assertNotIn(self, member: Any, container: Any, msg: str = None):
        """
        Assert that the member is not in the container

        :param member: Member comparison element
        :param container: Container comparison element
        :param msg: optional string message
        """
        self.assertIsNotNone(container, msg=msg)
        self.test_case.assertNotIn(member, container, msg=msg)

    # pylint: disable=invalid-name
    def assertIsInstance(self, obj: Any, cls: Any, msg: str = None):
        """
        Assert that the obj is an instance of the cls

        :param obj: object instance comparison element
        :param cls: Class comparison element
        :param msg: optional string message
        """
        self.test_case.assertIsInstance(obj, cls, msg=msg)

    # pylint: disable=invalid-name
    def assertNotIsInstance(self, obj: Any, cls: Any, msg: str = None):
        """
        Assert that the obj is not an instance of the cls

        :param obj: object instance comparison element
        :param cls: Class comparison element
        :param msg: optional string message
        """
        self.test_case.assertNotIsInstance(obj, cls, msg=msg)

    # pylint: disable=invalid-name
    def assertGreater(self, first: Any, second: Any, msg: str = None):
        """
        Assert that the first is greater than the second.

        :param first: First comparison element
        :param second: Second comparison element
        :param msg: optional string message
        """
        self.test_case.assertGreater(first, second, msg=msg)

    # pylint: disable=invalid-name
    def assertGreaterEqual(self, first: Any, second: Any, msg: str = None):
        """
        Assert that the first is greater than or equal to the second.

        :param first: First comparison element
        :param second: Second comparison element
        :param msg: optional string message
        """
        self.test_case.assertGreaterEqual(first, second, msg=msg)

    # pylint: disable=invalid-name
    def assertLess(self, first: Any, second: Any, msg: str = None):
        """
        Assert that the first is less than the second.

        :param first: First comparison element
        :param second: Second comparison element
        :param msg: optional string message
        """
        self.test_case.assertLess(first, second, msg=msg)

    # pylint: disable=invalid-name
    def assertLessEqual(self, first: Any, second: Any, msg: str = None):
        """
        Assert that the first is less than or equal to the second.

        :param first: First comparison element
        :param second: Second comparison element
        :param msg: optional string message
        """
        self.test_case.assertLessEqual(first, second, msg=msg)

    # pylint: disable=invalid-name
    def assertGist(self, gist: bool, acceptance_criteria: str, text_sample: str, msg: str = None):
        """
        Assert that the gist is true

        :param gist: Pass/Fail value of the gist expected to be True
        :param acceptance_criteria: The value to verify against
        :param text_sample: The value appearing in the test sample
        :param msg: optional string message
        """
        if msg is None:
            msg = f"""
text_sample unexpectedly did not match acceptance criteria.

text_sample:
{text_sample}

acceptance_criteria:
{acceptance_criteria}
"""
        self.test_case.assertTrue(gist, msg=msg)

    # pylint: disable=invalid-name
    def assertNotGist(self, gist: bool, acceptance_criteria: str, text_sample: str, msg: str = None):
        """
        Assert that the gist is true

        :param gist: Pass/Fail value of the gist expected to be False
        :param acceptance_criteria: The value to verify against
        :param text_sample: The value appearing in the test sample
        :param msg: optional string message
        """
        if msg is None:
            msg = f"""
text_sample unexpectedly did match acceptance criteria.

text_sample:
{text_sample}

acceptance_criteria:
{acceptance_criteria}
"""
        self.test_case.assertFalse(gist, msg=msg)
