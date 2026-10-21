
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

from enum import Enum


class McpError(Enum):
    """
    Enum class for standard MCP error codes and brief messages.
    """
    # Standard and additional JSON-RPC 2.0 errors;
    # we keep naming consistent with JSON-RPC 2.0 spec.
    # pylint: disable=invalid-name
    ParseError = (-32700, "Parse error")
    InvalidRequest = (-32600, "Invalid Request")
    NoMethod = (-32601, "Method not found")
    InvalidParams = (-32602, "Invalid params")
    InternalError = (-32603, "Internal error")
    ServerError = (-32000, "Server error")
    InvalidSession = (-33000, "Invalid Session")
    InvalidProtocolVersion = (-33001, "Invalid Protocol Version")

    def __init__(self, num_value, str_label):
        self.num_value = num_value
        self.str_label = str_label
