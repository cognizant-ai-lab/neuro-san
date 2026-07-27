
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

from neuro_san.internals.utils.exception_util import ExceptionUtil


class TestExceptionUtil:
    """Test suite for ExceptionUtil"""

    def test_plain_exception(self):
        """A regular exception yields a single 'Type: message' line."""
        details: str = ExceptionUtil.get_exception_details(ValueError("bad value"))
        assert details == "ValueError: bad value\n"

    def test_exception_group_is_unwrapped(self):
        """Sub-exceptions of an ExceptionGroup are listed with their own type and message."""
        group = ExceptionGroup(
            "unhandled errors in a TaskGroup",
            [ConnectionError("All connection attempts failed")],
        )

        details: str = ExceptionUtil.get_exception_details(group)

        assert "ExceptionGroup: unhandled errors in a TaskGroup" in details
        assert "Sub-exception 1:" in details
        assert "ConnectionError: All connection attempts failed" in details

    def test_nested_exception_groups(self):
        """Groups within groups are recursively expanded with increasing indentation."""
        inner = ExceptionGroup("inner", [TimeoutError("timed out")])
        outer = ExceptionGroup("outer", [inner, ValueError("bad value")])

        details: str = ExceptionUtil.get_exception_details(outer)

        assert "Sub-exception 2:" in details
        assert "TimeoutError: timed out" in details
        assert "ValueError: bad value" in details
