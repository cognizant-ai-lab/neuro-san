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

from tests.load_tests.traffic.load_test_assert_forwarder import LoadTestAssertForwarder


class TestLoadTestAssertForwarder(TestCase):
    """
    Unit tests for LoadTestAssertForwarder: a passing check returns, a failing one raises AssertionError
    with its unittest-style message, or with the caller's message when there is one.
    """

    def test_passing_checks_return(self) -> None:
        """
        Every assert method returns quietly when its check holds.
        """
        forwarder: LoadTestAssertForwarder = LoadTestAssertForwarder()
        forwarder.assertEqual(1, 1)
        forwarder.assertNotEqual(1, 2)
        forwarder.assertTrue(True)
        forwarder.assertFalse(False)
        forwarder.assertIs(None, None)
        forwarder.assertIsNot(1, None)
        forwarder.assertIsNone(None)
        forwarder.assertIsNotNone(1)
        forwarder.assertIn("a", "abc")
        forwarder.assertNotIn("x", "abc")
        forwarder.assertIsInstance(1, int)
        forwarder.assertNotIsInstance(1, str)
        forwarder.assertGreater(2, 1)
        forwarder.assertGreaterEqual(2, 2)
        forwarder.assertLess(1, 2)
        forwarder.assertLessEqual(2, 2)
        forwarder.assertGist(True, "a greeting", "hello")
        forwarder.assertNotGist(False, "a greeting", "goodbye")

    def test_failing_check_gives_the_default_message(self) -> None:
        """
        A failing check without a message raises AssertionError with the unittest-style message.
        """
        forwarder: LoadTestAssertForwarder = LoadTestAssertForwarder()
        with self.assertRaises(AssertionError) as caught:
            forwarder.assertIn("x", "abc")
        message: str = str(caught.exception)
        self.assertEqual("'x' not found in 'abc'", message)

    def test_failing_check_gives_the_callers_message(self) -> None:
        """
        A failing check with a message raises AssertionError with that message.
        """
        forwarder: LoadTestAssertForwarder = LoadTestAssertForwarder()
        with self.assertRaises(AssertionError) as caught:
            forwarder.assertIsNotNone(None, "sly_data.reservation_id is None")
        message: str = str(caught.exception)
        self.assertEqual("sly_data.reservation_id is None", message)

    def test_failing_gist_names_the_criteria(self) -> None:
        """
        A failing gist check names its acceptance criteria.
        """
        forwarder: LoadTestAssertForwarder = LoadTestAssertForwarder()
        with self.assertRaises(AssertionError) as caught:
            forwarder.assertGist(False, "a greeting", "goodbye")
        message: str = str(caught.exception)
        self.assertEqual("text_sample did not match acceptance criteria: 'a greeting'", message)
