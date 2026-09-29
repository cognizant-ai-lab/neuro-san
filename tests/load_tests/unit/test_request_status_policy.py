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

from tests.load_tests.config import STATUS_CREATED
from tests.load_tests.config import STATUS_FAILED
from tests.load_tests.config import STATUS_TIMEOUT
from tests.load_tests.traffic.request_status_policy import RequestStatusPolicy


class TestRequestStatusPolicy(TestCase):
    """Tests for RequestStatusPolicy."""

    def test_timed_out_at_and_past_the_cap(self) -> None:
        """Elapsed equal to or past the cap is a timeout; below it is not."""
        policy: RequestStatusPolicy = RequestStatusPolicy(timeout=10.0)
        self.assertFalse(policy.is_timed_out(9.99))
        self.assertTrue(policy.is_timed_out(10.0))
        self.assertTrue(policy.is_timed_out(10.5))

    def test_status_for_timeout_wins_over_answer(self) -> None:
        """A late answer is still a TIMEOUT."""
        policy: RequestStatusPolicy = RequestStatusPolicy(timeout=10.0)
        self.assertEqual(policy.status_for(10.0, "answer"), STATUS_TIMEOUT)

    def test_status_for_empty_answer_is_failed(self) -> None:
        """No answer text within the cap is FAILED."""
        policy: RequestStatusPolicy = RequestStatusPolicy(timeout=10.0)
        self.assertEqual(policy.status_for(1.0, ""), STATUS_FAILED)

    def test_status_for_error_is_failed(self) -> None:
        """A raised request within the cap is FAILED even with answer text."""
        policy: RequestStatusPolicy = RequestStatusPolicy(timeout=10.0)
        self.assertEqual(policy.status_for(1.0, "answer", "Traceback"), STATUS_FAILED)

    def test_status_for_answer_is_created(self) -> None:
        """Answer text within the cap is CREATED."""
        policy: RequestStatusPolicy = RequestStatusPolicy(timeout=10.0)
        self.assertEqual(policy.status_for(1.0, "answer"), STATUS_CREATED)
