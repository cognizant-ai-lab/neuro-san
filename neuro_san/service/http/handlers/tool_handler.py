
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
Handler for the Agent Web POST /api/v1/{agent_name}/tool/{tool_name} endpoint.

Invokes a single server-side CodedTool inside the network, applies sly_data
redaction at the boundary, and returns the result.

This is the "fetch back to origin" piece of the Agent Web model. See
docs/agent_web_design.md (§5.4).
"""
import asyncio
import importlib
import json
import os
from http import HTTPStatus
from typing import Any
from typing import Dict
from typing import Optional
from typing import Type

from leaf_common.config.resolver import Resolver
from leaf_common.parsers.dictionary_extractor import DictionaryExtractor

from neuro_san.interfaces.coded_tool import CodedTool
from neuro_san.internals.graph.activations.sly_data_redactor import SlyDataRedactor
from neuro_san.internals.graph.registry.activation_factory import ActivationFactory
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.interfaces.storage_class import StorageClass
from neuro_san.internals.network_providers.agent_network_storage import AgentNetworkStorage
from neuro_san.service.http.handlers.base_request_handler import BaseRequestHandler


class ToolHandler(BaseRequestHandler):
    """
    Invoke a single CodedTool inside a distributable network on this server.
    """

    # pylint: disable=arguments-differ
    async def post(self, agent_name: str, tool_name: str):
        """
        :param agent_name: The distributable network's name.
        :param tool_name: The CodedTool agent name inside that network.
        """
        metadata: Dict[str, Any] = self.get_metadata()
        status_code, err_message = self.application.try_start_client_request(
            metadata, f"{agent_name}/tool/{tool_name}"
        )
        if status_code != HTTPStatus.OK:
            self.do_finish(status_code, err_message)
            return

        # CORS for browser-direct fetches.
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Content-Type", "application/json")

        try:
            agent_network: AgentNetwork = self._lookup_network(agent_name)
            if agent_network is None:
                self.do_finish(
                    HTTPStatus.NOT_FOUND,
                    f"Agent network {agent_name!r} is not distributable on this server.",
                )
                return

            agent_spec: Optional[Dict[str, Any]] = agent_network.get_agent_tool_spec(tool_name)
            if agent_spec is None:
                self.do_finish(
                    HTTPStatus.NOT_FOUND,
                    f"Tool {tool_name!r} not found in network {agent_name!r}.",
                )
                return

            # Must be a server-side coded tool. client_side tools are not callable
            # via this endpoint — they ship to the runtime.
            if agent_spec.get("client_side"):
                self.do_finish(
                    HTTPStatus.BAD_REQUEST,
                    f"Tool {tool_name!r} is client-side; it cannot be invoked via /tool/.",
                )
                return
            class_ref: Optional[str] = agent_spec.get("class")
            if class_ref is None or not isinstance(class_ref, str):
                self.do_finish(
                    HTTPStatus.BAD_REQUEST,
                    f"Tool {tool_name!r} is not a CodedTool (no 'class' field).",
                )
                return

            # Parse {args, sly_data} from request body.
            try:
                request_dict: Dict[str, Any] = json.loads(self.request.body or b"{}")
            except json.JSONDecodeError as exc:
                self.do_finish(HTTPStatus.BAD_REQUEST, f"Invalid JSON: {exc}")
                return
            incoming_args: Dict[str, Any] = request_dict.get("args") or {}
            incoming_sly: Dict[str, Any] = request_dict.get("sly_data") or {}
            if not isinstance(incoming_args, dict) or not isinstance(incoming_sly, dict):
                self.do_finish(
                    HTTPStatus.BAD_REQUEST,
                    "Request body must be {\"args\": {...}, \"sly_data\": {...}}.",
                )
                return

            # Apply allow.to_downstream.sly_data on receipt as defense-in-depth.
            sly_data: Dict[str, Any] = self._redact_incoming(agent_spec, incoming_sly)

            # Merge any hard-coded args from the spec, like ActivationFactory does.
            merged_args: Dict[str, Any] = self._merge_args(incoming_args, agent_spec)

            # Resolve and instantiate the CodedTool.
            factory = ActivationFactory(agent_network)
            cls: Type[Any] = self._resolve_tool_class(class_ref, factory.get_agent_tool_path())
            if not issubclass(cls, CodedTool):
                self.do_finish(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    f"Resolved class {class_ref!r} is not a CodedTool.",
                )
                return

            tool_instance: CodedTool = cls()

            # Invoke. The CodedTool may mutate sly_data in place; we capture that.
            tool_output: Any = None
            tool_error: bool = False
            try:
                try:
                    tool_output = await tool_instance.async_invoke(merged_args, sly_data)
                except NotImplementedError:
                    # Fall back to the sync invoke().
                    loop = asyncio.get_event_loop()
                    tool_output = await loop.run_in_executor(
                        None, tool_instance.invoke, merged_args, sly_data
                    )
            # pylint: disable=broad-exception-caught
            except Exception as exc:
                tool_error = True
                tool_output = f"Error: {exc}"
                self.logger.error(metadata, "tool %s/%s raised: %s", agent_name, tool_name, exc)

            # Apply allow.from_downstream.sly_data on the way back to the caller.
            outgoing_sly: Dict[str, Any] = self._redact_outgoing(agent_spec, sly_data)

            self.write(
                json.dumps(
                    {
                        "tool_output": tool_output,
                        "sly_data": outgoing_sly,
                        "tool_error": tool_error,
                    }
                )
            )
        # pylint: disable=broad-exception-caught
        except Exception as exc:
            self.process_exception(exc)
        finally:
            self.do_finish()
            self.application.finish_client_request(metadata, f"{agent_name}/tool/{tool_name}")

    async def options(self, *_args, **_kwargs):
        """CORS preflight."""
        self.set_header("Access-Control-Allow-Origin", "*")
        self.set_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.set_header("Access-Control-Allow-Headers", "Content-Type")
        self.set_status(HTTPStatus.NO_CONTENT)
        self.do_finish()

    # ---- helpers ------------------------------------------------------------

    def _lookup_network(self, agent_name: str) -> Optional[AgentNetwork]:
        network_storage_dict: Dict[str, AgentNetworkStorage] = (
            self.server_context.get_network_storage_dict()
        )
        public_storage: AgentNetworkStorage = network_storage_dict.get(StorageClass.PUBLIC)
        if public_storage is None:
            return None
        # pylint: disable=protected-access
        agent_network: AgentNetwork = public_storage.agents_table.get(agent_name)
        if agent_network is None:
            return None
        if not agent_network.is_distributable():
            return None
        return agent_network

    @staticmethod
    def _merge_args(llm_args: Dict[str, Any], agent_spec: Dict[str, Any]) -> Dict[str, Any]:
        """Hard-coded args from the spec win over caller-provided args."""
        config_args: Dict[str, Any] = agent_spec.get("args") or {}
        if not config_args:
            return dict(llm_args)
        merged: Dict[str, Any] = dict(llm_args)
        merged.update(config_args)
        return merged

    @staticmethod
    def _redact_incoming(agent_spec: Dict[str, Any], sly_data: Dict[str, Any]) -> Dict[str, Any]:
        """Apply allow.to_downstream.sly_data on receipt (defense in depth)."""
        # If the agent does not declare any allow rules, default to letting
        # everything through (the caller's RemoteToolActivation already
        # applied the same rule on the way out — re-applying it here would
        # zero everything out unnecessarily).
        extractor = DictionaryExtractor(agent_spec)
        if extractor.get("allow.to_downstream.sly_data") is None:
            return dict(sly_data)
        redactor = SlyDataRedactor(
            agent_spec,
            config_keys=["allow.to_downstream.sly_data"],
            allow_empty_dict=True,
        )
        return redactor.filter_config(sly_data) or {}

    @staticmethod
    def _redact_outgoing(agent_spec: Dict[str, Any], sly_data: Dict[str, Any]) -> Dict[str, Any]:
        """Apply allow.from_downstream.sly_data to outgoing sly_data."""
        extractor = DictionaryExtractor(agent_spec)
        if extractor.get("allow.from_downstream.sly_data") is None:
            # If unset, default to redacting everything (security by default).
            return {}
        redactor = SlyDataRedactor(
            agent_spec,
            config_keys=["allow.from_downstream.sly_data"],
            allow_empty_dict=True,
        )
        return redactor.filter_config(sly_data) or {}

    @staticmethod
    def _resolve_tool_class(class_ref: str, agent_tool_path: str) -> Type[Any]:
        """Resolve `class_ref` to a real Python class using the same strategies
        as AbstractClassActivation."""
        # Try fully qualified first.
        if "." in class_ref:
            module_name, class_name = class_ref.rsplit(".", 1)
            try:
                module = importlib.import_module(module_name)
                return getattr(module, class_name)
            except (ImportError, AttributeError):
                pass

        # Fall back to AGENT_TOOL_PATH-style resolution.
        parts = class_ref.split(".")
        class_name = parts[-1]
        module_path = ".".join(parts[:-1]) if len(parts) > 1 else class_name.lower()
        agent_tool_path_parts = agent_tool_path.split(".")

        # Walk from most specific to most general, like AbstractClassActivation.
        for i in range(len(agent_tool_path_parts) + 1):
            current = ".".join(agent_tool_path_parts[: len(agent_tool_path_parts) - i])
            if not current:
                continue
            try:
                resolver = Resolver([current])
                cls = resolver.resolve_class_in_module(class_name, module_path)
                if cls is not None:
                    return cls
            except (ValueError, AttributeError, ImportError):
                continue

        raise ValueError(
            f"Cannot resolve tool class {class_ref!r} under AGENT_TOOL_PATH "
            f"{os.environ.get('AGENT_TOOL_PATH', '<default>')}"
        )
