
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
ClientSideToolActivation - execute a CodedTool whose Python source was
shipped to the runtime as part of an Agent Web published network.

This activation only fires on the runtime ("browser") side, where a scrubbed
wire config has been loaded. The original server-side neuro-san process
running its own HOCON never sees `client_side_source` and therefore never
goes through this path.

Security model:
  - The source bytes are verified against the `integrity` hash stamped by the
    scrubber. A mismatch raises before exec().
  - Source is compiled in a fresh empty namespace, NOT injected into sys.modules.
    Once the activation completes, the class and source are GC-eligible.
  - The intended deployment context is a wasm-sandboxed runtime (Pyodide /
    JupyterLite). When run in a non-sandboxed Python process (e.g. the
    headless browser CLI), the integrity-checked source is still executed
    with whatever privileges the host process has — operators of that CLI
    must understand this is the "trusted-local app" tier, not the "browser"
    tier. See docs/agent_web_design.md (§9).
"""
import base64
import hashlib
from typing import Any
from typing import Dict
from typing import Type

from neuro_san.internals.graph.activations.abstract_class_activation import AbstractClassActivation
from neuro_san.internals.graph.interfaces.agent_tool_factory import AgentToolFactory
from neuro_san.internals.run_context.interfaces.run_context import RunContext


class ClientSideToolActivation(AbstractClassActivation):
    """
    AbstractClassActivation subclass that uses a class compiled in-process from
    base64-encoded source shipped in the agent spec, rather than resolving a
    class via AGENT_TOOL_PATH.
    """

    # pylint: disable=too-many-arguments,too-many-positional-arguments
    def __init__(self,
                 parent_run_context: RunContext,
                 factory: AgentToolFactory,
                 arguments: Dict[str, Any],
                 agent_tool_spec: Dict[str, Any],
                 sly_data: Dict[str, Any]):
        # AbstractClassActivation's __init__ runs before we can compile, but it
        # does not invoke resolve_class — it only sets up the run context and
        # argument plumbing. The compile happens lazily in get_full_class_ref /
        # resolve_class.
        super().__init__(parent_run_context, factory, arguments, agent_tool_spec, sly_data)

        # Compile up front so any integrity / syntax errors surface at activation
        # construction time rather than mid-LLM-call.
        self._compiled_class: Type[Any] = self._compile_class_from_spec(agent_tool_spec)

    def get_full_class_ref(self) -> str:
        """Synthetic ref — only used in log messages."""
        class_name: str = self.agent_tool_spec.get("client_side_class") or "ClientSideTool"
        return f"client_side.{class_name}"

    # Override resolve_class to short-circuit the AGENT_TOOL_PATH walk.
    # pylint: disable=unused-argument
    def resolve_class(self, class_name: str, module_name: str):
        return self._compiled_class

    @staticmethod
    def _compile_class_from_spec(agent_tool_spec: Dict[str, Any]) -> Type[Any]:
        """
        Decode + integrity-check + exec the shipped source, return the class.
        """
        source_b64: str = agent_tool_spec.get("client_side_source") or ""
        if not source_b64:
            raise ValueError(
                "ClientSideToolActivation: missing 'client_side_source' in agent spec"
            )
        try:
            source_bytes: bytes = base64.b64decode(source_b64)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"ClientSideToolActivation: bad base64 in client_side_source: {exc}"
            ) from exc

        # Integrity check.
        expected_integrity: str = agent_tool_spec.get("integrity") or ""
        if expected_integrity:
            digest = hashlib.sha256(source_bytes).hexdigest()
            actual_integrity = f"sha256-{digest}"
            if actual_integrity != expected_integrity:
                raise ValueError(
                    "ClientSideToolActivation: integrity check failed for "
                    f"client_side tool {agent_tool_spec.get('name')!r}. "
                    f"Expected {expected_integrity!r}, computed {actual_integrity!r}."
                )

        class_name: str = agent_tool_spec.get("client_side_class") or ""
        if not class_name:
            raise ValueError(
                "ClientSideToolActivation: missing 'client_side_class' in agent spec"
            )

        # Compile and exec in a fresh namespace. Synthetic file path for tracebacks.
        synthetic_path = f"<agent_web:{agent_tool_spec.get('name', class_name)}>"
        code = compile(source_bytes, synthetic_path, "exec")
        namespace: Dict[str, Any] = {"__name__": f"agent_web_client_{class_name}"}
        exec(code, namespace)  # noqa: S102 - intentional, content is integrity-checked

        cls = namespace.get(class_name)
        if cls is None:
            raise ValueError(
                f"ClientSideToolActivation: class {class_name!r} not defined "
                f"in shipped source for agent {agent_tool_spec.get('name')!r}"
            )
        return cls
