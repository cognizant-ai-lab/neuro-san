
# Copyright (C) 2023-2025 Cognizant Digital Business, Evolutionary AI.
# All Rights Reserved.
# Issued under the Academic Public License.
#
# You can be released from the terms, and requirements of the Academic Public
# License by purchasing a commercial license.
# Purchase of a commercial license is mandatory for any use of the
# neuro-san SDK Software in commercial settings.
#
# END COPYRIGHT
"""
See class comment for details
"""
from typing import Any
from typing import Dict

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
        update_done: bool = await self.update_agents(metadata=metadata)
        if not update_done:
            return

        service: AsyncAgentService = self.agent_policy.allow(agent_name)
        if service is None:
            self.set_status(404)
            self.logger.error({}, "error: Invalid request path %s", self.request.path)
            self.do_finish()
            return

        self.application.start_client_request(metadata, f"{agent_name}/connectivity")
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
