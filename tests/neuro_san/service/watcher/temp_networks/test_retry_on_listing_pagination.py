
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
S3ReservationsStorage.iter_reservation_keys() lists S3 objects via a
boto3 paginator. boto3 paginators are *lazy*: paginator.paginate(...)
returns a PageIterator that performs no S3 call at construction time;
the actual ListObjectsV2 HTTP requests happen during iteration.

The original implementation wrapped only the paginator-creation call in
_do_with_retries, which never hit a retryable error because it never
made a network call. Transient ClientError/BotoCoreError raised
mid-iteration therefore bypassed the retry wrapper entirely.

This module exercises the fixed implementation: the per-page next()
call is what _do_with_retries wraps, so a one-shot ThrottlingException
on the first page fetch is retried and the listing recovers.
"""
from unittest.mock import patch

from tests.neuro_san.service.watcher.temp_networks._fake_page_iterator \
    import FakePageIterator
from tests.neuro_san.service.watcher.temp_networks._fake_paginator \
    import FakePaginator
from tests.neuro_san.service.watcher.temp_networks._test_base \
    import S3ReservationsStorageTestBase


class TestRetryOnListingPagination(S3ReservationsStorageTestBase):
    """
    Verifies that iter_reservation_keys() recovers from a transient
    ClientError raised by the boto3 paginator mid-iteration. The fix
    moved _do_with_retries from around paginator construction (a
    constant-time call that does no S3 work) to around each per-page
    next() call (where the ListObjectsV2 HTTP request actually
    happens).
    """

    def test_iter_reservation_keys_retries_on_throttling_mid_iteration(self):
        """
        On a transient ThrottlingException raised by the first page
        fetch, iter_reservation_keys() should retry the next() call.
        The retry should succeed and the listing should yield every
        key from every configured page in order, with no keys lost
        from the failed first attempt.
        """
        # Two pages, three keys total. The first __next__ on the page
        # iterator raises a throttle; the retry returns page 1; the
        # call after that returns page 2; the call after that raises
        # StopIteration (caught by next(it, sentinel) in the production
        # code, signaling end-of-iteration without an exception).
        pages = [
            {"Contents": [
                {"Key": "reservations/copy_cat-test-UUID-0001.json"},
                {"Key": "reservations/copy_cat-test-UUID-0002.json"},
            ]},
            {"Contents": [
                {"Key": "reservations/copy_cat-test-UUID-0003.json"},
            ]},
        ]
        page_iter = FakePageIterator(pages, fail_on_calls={1})
        paginator = FakePaginator(page_iter)

        # Inject a paginator factory onto the in-memory FakeS3Client for
        # the duration of this test only. The base-class fake does not
        # ship with get_paginator because no earlier test needed
        # pagination.
        # pylint: disable=unused-argument
        def get_paginator(name):
            """Stand-in for boto3 Client.get_paginator; ignores its operation-name arg."""
            return paginator

        self.fake_s3.get_paginator = get_paginator

        # Skip the real exponential-backoff sleep so the test stays
        # fast. Patches the module-local time.sleep symbol that
        # _do_with_retries uses.
        with patch(
            "neuro_san.service.watcher.temp_networks."
            "s3_reservations_storage.time.sleep"
        ):
            keys = list(self.storage.iter_reservation_keys())

        # Every configured key is yielded exactly once, in page order.
        # This would have failed under the original implementation: the
        # mid-iteration throttle would have aborted the whole listing.
        self.assertEqual(
            [
                "reservations/copy_cat-test-UUID-0001.json",
                "reservations/copy_cat-test-UUID-0002.json",
                "reservations/copy_cat-test-UUID-0003.json",
            ],
            keys,
            f"Expected all configured page keys to be yielded after retry; got {keys}.",
        )

        # __next__ was invoked exactly four times: 1 throttled, then
        # 1 retry that returned page 1, 1 that returned page 2, 1 that
        # signaled end-of-iteration. Catches "no retry happened"
        # (count == 3 with the throttle propagating out) and
        # "over-retried beyond what we expect" (count > 4).
        self.assertEqual(
            4,
            page_iter.call_count,
            f"Expected exactly 4 paginator __next__ calls (1 throttled + "
            f"2 successful + 1 end-of-iteration); got {page_iter.call_count}.",
        )
