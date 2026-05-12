
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
See class comment for details
"""
from typing import Any
from typing import Dict

from neuro_san.service.http.logging.http_logger import HttpLogger
from neuro_san.service.utils.request_util import RequestUtil


class McpResourcesProcessor:
    """
    Class implementing "resources"-related MCP requests.
    Overall MCP documentation can be found here:
    https://modelcontextprotocol.io/specification/2025-06-18/server/resources
    """

    def __init__(self, logger: HttpLogger):
        self.logger: HttpLogger = logger

    async def list_resources(self, request_id, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """
        List available MCP resources.
        :param request_id: MCP request id;
        :param metadata: http-level request metadata;
        :return: json dictionary with resources list in MCP format
        """
        _ = metadata
        return {
            "jsonrpc": "2.0",
            "id": RequestUtil.safe_request_id(request_id),
            "result": {
                "resources": []
            }
        }
