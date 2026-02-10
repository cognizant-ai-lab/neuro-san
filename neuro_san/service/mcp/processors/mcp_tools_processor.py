
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
from typing import List
from typing import Tuple

import asyncio
import contextlib
import json
import tornado

from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.interfaces.agent_network_provider import AgentNetworkProvider
from neuro_san.internals.network_providers.agent_network_storage import AgentNetworkStorage
from neuro_san.service.http.interfaces.agent_authorizer import AgentAuthorizer
from neuro_san.service.generic.async_agent_service import AsyncAgentService
from neuro_san.service.generic.async_agent_service_provider import AsyncAgentServiceProvider
from neuro_san.service.mcp.util.mcp_errors_util import McpErrorsUtil
from neuro_san.service.mcp.util.mcp_request_util import McpRequestUtil
from neuro_san.service.mcp.validation.tool_request_validator import ToolRequestValidator
from neuro_san.service.http.logging.http_logger import HttpLogger


class McpToolsProcessor:
    """
    Class implementing "tools"-related MCP requests.
    Overall MCP documentation can be found here:
    https://modelcontextprotocol.io/specification/2025-06-18/server/tools
    """

    def __init__(self,
                 logger: HttpLogger,
                 network_storage_dict: AgentNetworkStorage,
                 agent_policy: AgentAuthorizer,
                 tool_request_validator: ToolRequestValidator):
        self.logger: HttpLogger = logger
        self.network_storage_dict: AgentNetworkStorage = network_storage_dict
        self.agent_policy: AgentAuthorizer = agent_policy
        self.tool_request_validator: ToolRequestValidator = tool_request_validator

    async def list_tools(self, request_id, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """
        List available MCP tools.
        :param request_id: MCP request id;
        :param metadata: http-level request metadata;
        :return: json dictionary with tools list in MCP format
        """
        public_storage: AgentNetworkStorage = self.network_storage_dict.get("public")
        tools_description: List[Dict[str, Any]] = []
        for agent_name in public_storage.get_agent_names():
            provider: AgentNetworkProvider = public_storage.get_agent_network_provider(agent_name)
            if provider is not None:
                agent_network: AgentNetwork = provider.get_agent_network()
                if agent_network.is_mcp_tool():
                    tool_dict: Dict[str, Any] = await self._get_tool_description(agent_name, metadata)
                    tools_description.append(tool_dict)
        return {
            "jsonrpc": "2.0",
            "id": McpRequestUtil.safe_request_id(request_id),
            "result": {
                "tools": tools_description
            }
        }

    async def call_tool(self, request_id, metadata: Dict[str, Any],
                        tool_name: str,
                        prompt: Dict[str, Any],
                        chat_context: Dict[str, Any],
                        chat_filter: Dict[str, Any],
                        sly_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Call MCP tool, which executes neuro-san agent chat request.
        :param request_id: MCP request id;
        :param metadata: http-level request metadata;
        :param tool_name: tool name;
        :param prompt: input prompt as a JSON structure;
        :param chat_context: chat context JSON structure, could be None;
        :param chat_filter: chat filter type JSON structure, could be None;
        :param sly_data: arbitrary JSON dictionary containing sly_data, could be None;
        :return: json dictionary with tool response in MCP format;
                 or json dictionary with error message in MCP format.
        """
        # pylint: disable=too-many-locals
        # pylint: disable=too-many-arguments
        # pylint: disable=too-many-positional-arguments

        service_provider: AsyncAgentServiceProvider = self.agent_policy.allow(tool_name)
        if service_provider is None:
            # No such tool is found:
            return McpErrorsUtil.get_tool_error(request_id, f"Tool not found: {tool_name}")
        service: AsyncAgentService = service_provider.get_service()
        if not service.is_mcp_tool():
            # Service is not allowed to be called as MCP tool:
            return McpErrorsUtil.get_tool_error(request_id, f"Service not available as MCP tool: {tool_name}")

        tool_timeout_seconds: float = service.get_request_timeout_seconds()
        if tool_timeout_seconds <= 0.0:
            # For asyncio.timeout(), None means no timeout:
            tool_timeout_seconds = None

        input_request: Dict[str, Any] = self._get_chat_input_request(prompt, chat_context, chat_filter, sly_data)
        response_text: str = ""
        response_structure: Dict[str, Any] = None
        try:
            async with asyncio.timeout(tool_timeout_seconds):
                result_generator = service.streaming_chat(input_request, metadata)
                async for result_dict in result_generator:
                    partial_response, structure_data = await self._extract_tool_response_part(result_dict)
                    if partial_response is not None:
                        response_text = response_text + partial_response
                    if structure_data is not None:
                        response_structure = structure_data

        except (asyncio.CancelledError, tornado.iostream.StreamClosedError):
            self.logger.info(metadata, "Tool execution %s cancelled/stream closed.", tool_name)
            return McpErrorsUtil.get_tool_error(request_id, f"Stream closed for tool {tool_name}")

        except asyncio.TimeoutError:
            self.logger.info(metadata,
                             "Chat tool timeout for %s in %f seconds.",
                             tool_name, tool_timeout_seconds)
            return McpErrorsUtil.get_tool_error(request_id, f"Timeout for tool {tool_name}")

        except Exception as exc:  # pylint: disable=broad-exception-caught
            self.logger.error(metadata, "Tool %s execution failed: %s", tool_name, str(exc))
            return McpErrorsUtil.get_tool_error(request_id, f"Failed to execute tool {tool_name}")

        finally:
            # We are done with the response stream,
            # ensure generator is closed properly in any case:
            if result_generator is not None:
                with contextlib.suppress(Exception):
                    # It is possible we will call .aclose() twice
                    # on our result_generator - it is allowed and has no effect.
                    await result_generator.aclose()

        # Return tool call result:
        call_result: Dict[str, Any] =\
            await self.build_tool_call_result(request_id, response_text, response_structure)
        return call_result

    async def build_tool_call_result(
            self,
            request_id,
            result_text: str,
            result_structure: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build MCP tool call result dictionary from given text and structure parts.
        :param request_id: MCP request id;
        :param result_text: tool call result text part;
        :param result_structure: tool call result structure part;
        :return: json dictionary with tool call result in MCP format;
        """

        call_result: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": McpRequestUtil.safe_request_id(request_id),
            "result": {
                "content": [
                    {
                        "type": "text",
                        "text": ""  # to be filled later
                    }
                ],
                "isError": False
            }
        }
        # Construct actual tool call result:
        if result_structure is not None:
            # "structuredContent" is MCP standard key for content with additional structure.
            call_result["result"]["structuredContent"] = result_structure
            # For backward compatibility, also add text version of structure:
            structure_data: Dict[str, Any] = result_structure.get("structure", None)
            if structure_data is not None:
                structure_str: str = f"```json\n{json.dumps(structure_data, indent=2)}\n```"
                result_text = result_text + structure_str
        call_result["result"]["content"][0]["text"] = McpRequestUtil.safe_message(result_text)
        return call_result

    async def _get_tool_description(self, agent_name: str, metadata: Dict[str, Any]) -> Dict[str, Any]:
        service_provider: AsyncAgentServiceProvider = self.agent_policy.allow(agent_name)
        if service_provider is None:
            return None
        service: AsyncAgentService = service_provider.get_service()
        function_dict: Dict[str, Any] = await service.function({}, metadata)
        tool_description: str = function_dict.get("function", {}).get("description", "")
        return {
            "name": agent_name,
            "description": tool_description,
            "inputSchema": self.tool_request_validator.get_request_schema()
        }

    async def _extract_tool_response_part(
            self, response_dict: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        """
        Extract the tool response part from the given streaming chat response dictionary.
        :param response_dict: streaming chat response dictionary;
        :return: tuple of 2 values:
            text part as string or None,
            structure part as dictionary or None
        """
        response_part_dict: Dict[str, Any] = response_dict.get("response", {})
        response_type: str = response_part_dict.get("type", "")
        if response_type == "AGENT_FRAMEWORK":
            text: str = response_part_dict.get("text", None)
            # For final response, there could be chat_context structured data we need to return:
            structure_data: Dict[str, Any] = self.construct_mcp_structed_content(response_part_dict)
            return text, structure_data
        return None, None

    def construct_mcp_structed_content(self, response_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Construct MCP structured content dictionary from the given streaming chat response dictionary.
        :param response_dict: streaming chat response dictionary;
        :return: structured content dictionary or None
        """
        # We are looking for 2 possible parts of structured content:
        # "structure" - that was optionally generated by an agent;
        # and "chat_context" - that allows the context of a continuing conversation to be reconstructed by a client.
        # If both are missing, we return None.
        structure_data: Dict[str, Any] = response_dict.get("structure", None)
        chat_context_data: Dict[str, Any] = response_dict.get("chat_context", None)
        if structure_data is None and chat_context_data is None:
            return None
        result: Dict[str, Any] = {}
        if structure_data is not None:
            result["structure"] = structure_data
        if chat_context_data is not None:
            result["chat_context"] = chat_context_data
        return result

    def _get_chat_input_request(self,
                                user_message: Dict[str, Any],
                                chat_context: Dict[str, Any],
                                chat_filter: Dict[str, Any],
                                sly_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Construct a Python dictionary expected by "streaming_chat" service API call.
        :param user_message: user message JSON structure;
        :param chat_context: chat context JSON structure, could be None;
        :param chat_filter: chat filter type JSON structure, could be None;
        :param sly_data: arbitrary JSON dictionary containing sly_data, could be None;
        :return: "streaming_chat" service API input dictionary
        """
        request_dict: Dict[str, Any] = {
            "user_message": user_message
        }
        if chat_filter is not None:
            request_dict["chat_filter"] = chat_filter
        if chat_context is not None:
            request_dict["chat_context"] = chat_context
        if sly_data is not None:
            request_dict["sly_data"] = sly_data
        return request_dict
