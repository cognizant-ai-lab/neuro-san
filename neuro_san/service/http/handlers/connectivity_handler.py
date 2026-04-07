
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

from http import HTTPStatus

from neuro_san.service.generic.async_agent_service import AsyncAgentService
from neuro_san.service.http.handlers.base_request_handler import BaseRequestHandler


class ConnectivityHandler(BaseRequestHandler):
    """
    Handler class for neuro-san "connectivity" API call.
    """

    async def get(self, agent_name: str):
        """
        Implementation of GET request handler for "connectivity" API call.
        """
        metadata: Dict[str, Any] = self.get_metadata()
        service: AsyncAgentService = await self.get_service(agent_name, metadata)
        if service is None:
            return

        status_code, err_message = self.application.try_start_client_request(metadata, f"{agent_name}/connectivity")
        if status_code != HTTPStatus.OK:
            self.do_finish(status_code, err_message)
            return

        try:
            data: Dict[str, Any] = {}
            result_dict: Dict[str, Any] = await service.connectivity(data, metadata)

            # Return response to the HTTP client
            self.set_header("Content-Type", "application/json")
            self.write(result_dict)

        except Exception as exc:  # pylint: disable=broad-exception-caught
            self.process_exception(exc)
        finally:
            self.do_finish()
            self.application.finish_client_request(metadata, f"{agent_name}/connectivity")
