
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
See class comment for details.
"""


class AgentSessionClosedError(Exception):
    """
    Raised when an operation is attempted on an AgentSession that has been
    close()-d.

    A remote session is single-use with respect to close(): once close() drops
    its connection, the session cannot be used again. Operations
    (streaming_chat / function / connectivity) then raise this error rather than
    silently returning nothing or masquerading as a lost connection, so callers
    can distinguish a deliberate cancellation/close from a genuine connectivity
    failure (which is still reported as a ValueError with debug help text).
    """
