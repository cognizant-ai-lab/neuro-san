
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
In-memory stand-in for a boto3 PageIterator used by the
S3ReservationsStorage pagination-retry test.

This module is intentionally named with a leading underscore so
pytest's default test-file pattern (test_*.py) skips it during
collection.
"""
from botocore.exceptions import ClientError


# pylint: disable=too-few-public-methods
class FakePageIterator:
    """
    Stand-in for a boto3 PageIterator. Yields the configured pages in
    order. For any 1-based call number listed in fail_on_calls, raises
    a retryable ClientError on that __next__ invocation instead of
    advancing -- this mirrors the real boto3 behavior where a failed
    page fetch does not advance the ContinuationToken, so a retried
    next() re-issues the same request.
    """

    def __init__(self, pages, fail_on_calls=()):
        self._pages = list(pages)
        self._index = 0
        self.call_count = 0
        self._fail_on_calls = set(fail_on_calls)

    def __iter__(self):
        return self

    def __next__(self):
        self.call_count += 1
        if self.call_count in self._fail_on_calls:
            # Match the shape of a real throttle: code + 503. The retry
            # path in _do_with_retries treats this as transient.
            raise ClientError(
                {
                    "Error": {"Code": "ThrottlingException"},
                    "ResponseMetadata": {"HTTPStatusCode": 503},
                },
                "ListObjectsV2",
            )
        if self._index >= len(self._pages):
            raise StopIteration
        page = self._pages[self._index]
        self._index += 1
        return page
