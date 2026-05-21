
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
In-memory stand-in for a boto3 Paginator used by the
S3ReservationsStorage pagination-retry test.

This module is intentionally named with a leading underscore so
pytest's default test-file pattern (test_*.py) skips it during
collection.
"""


# pylint: disable=too-few-public-methods
class FakePaginator:
    """
    Stand-in for a boto3 Paginator. paginate() returns the page iterator
    that was injected by the test, ignoring its keyword arguments
    (Bucket/Prefix/PaginationConfig).
    """

    def __init__(self, page_iterator):
        self._page_iterator = page_iterator

    # pylint: disable=unused-argument
    def paginate(self, **kwargs):
        """Stand-in for boto3 Paginator.paginate; ignores its keyword arguments."""
        return self._page_iterator
