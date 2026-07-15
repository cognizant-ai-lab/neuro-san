
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
S3ReservationsStorage.iter_reservation_keys() pages through S3 by
calling list_objects_v2 directly with ContinuationToken, with each
call wrapped in _do_with_retries. This module exercises that retry
behavior: a transient ThrottlingException on the first page-fetch
attempt is retried, the retry succeeds, pagination continues, and the
listing yields every key in order.
"""
from unittest.mock import MagicMock
from unittest.mock import patch

from botocore.exceptions import ClientError

from tests.neuro_san.service.watcher.temp_networks.s3_reservations_storage_test_base \
    import S3ReservationsStorageTestBase


class TestRetryOnListingPagination(S3ReservationsStorageTestBase):
    """
    Verifies that iter_reservation_keys() recovers from a transient
    ClientError raised by list_objects_v2 and correctly threads the
    ContinuationToken across multiple pages.
    """

    def test_iter_reservation_keys_retries_on_throttling_first_page(self):
        """
        On a transient ThrottlingException raised by the first
        list_objects_v2 call, iter_reservation_keys() should retry. The
        retry should succeed and pagination should continue using the
        NextContinuationToken returned by the page-1 response. All
        configured keys should be yielded in page order, with no keys
        lost from the failed first attempt.
        """
        # Two-page listing. Page 1 reports IsTruncated=True with a
        # NextContinuationToken; page 2 reports IsTruncated=False and so
        # ends the loop.
        page_one_response = {
            "Contents": [
                {"Key": "reservations/copy_cat-test-UUID-0001.json"},
                {"Key": "reservations/copy_cat-test-UUID-0002.json"},
            ],
            "IsTruncated": True,
            "NextContinuationToken": "page-2-token",
        }
        page_two_response = {
            "Contents": [
                {"Key": "reservations/copy_cat-test-UUID-0003.json"},
            ],
            "IsTruncated": False,
        }
        throttle_error = ClientError(
            {
                "Error": {"Code": "ThrottlingException"},
                "ResponseMetadata": {"HTTPStatusCode": 503},
            },
            "ListObjectsV2",
        )

        # The side_effect sequence drives the in-order call semantics:
        # call 1 raises (the throttle), call 2 returns page 1 (the retry),
        # call 3 returns page 2. MagicMock raises StopIteration if the
        # production code calls more times than expected, which surfaces
        # over-retry regressions as a hard test failure.
        list_objects_v2 = MagicMock(
            side_effect=[throttle_error, page_one_response, page_two_response]
        )

        # Inject onto the in-memory FakeS3Client for the duration of this
        # test only; the base-class fake does not ship with list_objects_v2
        # because no earlier test needed it.
        self.fake_s3.list_objects_v2 = list_objects_v2

        # Skip the real exponential-backoff sleep so the test stays fast.
        # Patches the module-local time.sleep symbol that _do_with_retries
        # uses.
        with patch(
            "neuro_san.service.watcher.temp_networks.s3_retry_util.sync_sleep"
        ):
            keys = list(self.storage.expiration.iter_reservation_keys(self.fake_s3))

        # Every configured key is yielded exactly once, in page order.
        # Under the original (paginator-based) implementation a mid-listing
        # throttle aborted the whole listing; the rewrite isolates the
        # retry to one page fetch at a time.
        self.assertEqual(
            [
                "reservations/copy_cat-test-UUID-0001.json",
                "reservations/copy_cat-test-UUID-0002.json",
                "reservations/copy_cat-test-UUID-0003.json",
            ],
            keys,
            f"Expected all configured page keys to be yielded after retry; got {keys}.",
        )

        # list_objects_v2 was invoked exactly three times: 1 throttled,
        # 1 retry that returned page 1, 1 that returned page 2. Catches
        # "no retry happened" (count == 1, throttle propagated out) and
        # "over-retried beyond what we expect" (count > 3).
        self.assertEqual(
            3,
            list_objects_v2.call_count,
            f"Expected exactly 3 list_objects_v2 calls (1 throttled + 1 retry + "
            f"1 second page); got {list_objects_v2.call_count}.",
        )

        # The first two calls (page 1 attempt + its retry) carry no
        # ContinuationToken; the third call carries the token returned in
        # page 1's response. Verifies that the production code (a) does
        # not advance the token until the page fetch actually succeeds,
        # and (b) threads the token from one response into the next request.
        actual_tokens = [
            call.kwargs.get("ContinuationToken")
            for call in list_objects_v2.call_args_list
        ]
        self.assertEqual(
            [None, None, "page-2-token"],
            actual_tokens,
            f"Expected ContinuationToken sequence [None, None, 'page-2-token']; "
            f"got {actual_tokens}.",
        )
