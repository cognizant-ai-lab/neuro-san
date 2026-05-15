
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
DistributableNetworkScrubber - transform an in-memory AgentNetwork's config
into the wire form that is safe to publish to runtimes ("browsers") that fetch
the network's notebook and execute it locally.

See docs/agent_web_design.md (§5.2) for the full specification.

The scrubber:
  - drops recognized server secrets from llm_config and any nested overrides;
  - rewrites server-side `class:` and `toolbox:` references into a
    `coded_tool_url` pointing back at the origin's per-tool RPC endpoint
    (the class identifier never leaves the server);
  - for tools marked `client_side: true`, ships the Python source inline
    (base64 + SHA-256 integrity hash);
  - stamps Agent Web protocol metadata on the wire form;
  - never mutates the input AgentNetwork.
"""
import base64
import copy
import hashlib
import importlib
import inspect
import re
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple

from leaf_common.config.resolver import Resolver

from neuro_san.internals.graph.registry.agent_network import AgentNetwork


# Agent Web protocol version emitted by this scrubber.
AGENT_WEB_PROTOCOL_VERSION: str = "0.1"

# Substring patterns (case-insensitive) used to identify secret-looking keys in
# llm_config dicts. Conservative: when in doubt the scrubber will strip.
DEFAULT_SECRET_KEY_PATTERNS: Tuple[str, ...] = (
    "api_key",
    "apikey",
    "api_secret",
    "secret",
    "token",
    "password",
    "passwd",
    "credential",
    "private_key",
    "aws_",
    "azure_",
)


class DistributableScrubberError(ValueError):
    """Raised when a scrubbed wire form fails post-conditions
    (e.g. a `class:` slipped through).  Operators must fix the network."""


class DistributableNetworkScrubber:
    """
    Pure-ish transform: AgentNetwork + origin -> wire-form dict.

    The instance is constructed with the resolution context needed to load
    client-side tool source files; calling .scrub() returns a fresh dict
    and never mutates the input AgentNetwork.
    """

    def __init__(self,
                 agent_tool_path: str,
                 secret_patterns: Optional[Tuple[str, ...]] = None):
        """
        :param agent_tool_path: The dotted-module agent tool path under which
                coded tools for the network can be resolved (same string the
                ActivationFactory uses; defaults pulled by callers from
                ActivationFactory.get_agent_tool_path()).
        :param secret_patterns: Optional override of the secret-key patterns
                used to strip llm_config entries. Case-insensitive substring match.
        """
        self.agent_tool_path: str = agent_tool_path
        self.secret_patterns: Tuple[str, ...] = (
            secret_patterns if secret_patterns is not None
            else DEFAULT_SECRET_KEY_PATTERNS
        )

    def scrub(self, agent_network: AgentNetwork, origin: str) -> Dict[str, Any]:
        """
        :param agent_network: AgentNetwork to publish to the Agent Web.
        :param origin: The fully-qualified origin URL (scheme://host[:port])
                where this network is being served. Used as the prefix for
                rewritten `coded_tool_url` values.
        :return: A wire-form dict ready to be embedded in a notebook raw cell.
                Caller may json.dumps() it directly.
        :raises DistributableScrubberError: if post-conditions fail.
        """
        # Defensive: deep-copy so we never mutate the live config.
        wire: Dict[str, Any] = copy.deepcopy(agent_network.get_config())

        # Top-level llm_config: strip secrets.
        if isinstance(wire.get("llm_config"), dict):
            wire["llm_config"] = self._strip_secrets(wire["llm_config"])

        # Per-agent rewrites.
        network_name: str = agent_network.get_network_name()
        new_tools: List[Dict[str, Any]] = []
        for agent_spec in wire.get("tools", []) or []:
            new_tools.append(self._rewrite_agent(agent_spec, origin, network_name))
        wire["tools"] = new_tools

        # Drop the commondefs block: substitution has already been applied
        # by AgentNetworkRestorer.filter_config when the network was loaded.
        wire.pop("commondefs", None)

        # Stamp protocol metadata so the runtime can recognize the document.
        wire["agent_web"] = {
            "protocol_version": AGENT_WEB_PROTOCOL_VERSION,
            "origin": origin,
            "network_name": network_name,
            "published_at": datetime.now(timezone.utc).isoformat(),
        }

        # Post-conditions: nothing the runtime could mis-execute should remain.
        self._enforce_post_conditions(wire)
        return wire

    # ---- internals ----------------------------------------------------------

    def _rewrite_agent(self,
                       agent_spec: Dict[str, Any],
                       origin: str,
                       network_name: str) -> Dict[str, Any]:
        """
        Rewrite one agent's spec into wire form.
        :return: a new dict (never the same object as agent_spec).
        """
        out: Dict[str, Any] = copy.deepcopy(agent_spec)

        # Strip any per-agent llm_config override too.
        if isinstance(out.get("llm_config"), dict):
            out["llm_config"] = self._strip_secrets(out["llm_config"])

        is_client_side: bool = bool(out.get("client_side", False))
        class_ref: Optional[str] = out.get("class")
        toolbox_ref: Optional[str] = out.get("toolbox")

        if class_ref is None and toolbox_ref is None:
            # Not a coded tool. Likely an LLM agent or a branch. Leave as-is
            # (but its `tools:` list — references to other agents within this
            # network or to external agents — does not need rewriting; both
            # are resolved at runtime).
            return out

        agent_name: str = self._agent_name(out)

        if is_client_side:
            if toolbox_ref is not None:
                # We cannot ship toolbox source from here; toolbox tools live
                # behind a registry concept that the runtime does not have
                # mirrored. Fall back to remote-tool semantics.
                out.pop("client_side", None)
                return self._make_remote(out, origin, network_name, agent_name)

            # Ship the Python source for this class to the runtime.
            source_bytes, integrity = self._load_class_source(class_ref)
            out.pop("class", None)
            out.pop("toolbox", None)
            out["client_side"] = True
            out["client_side_class"] = class_ref.rsplit(".", 1)[-1]
            out["client_side_source"] = base64.b64encode(source_bytes).decode("ascii")
            out["integrity"] = integrity
            return out

        # Server-side default: rewrite to coded_tool_url.
        return self._make_remote(out, origin, network_name, agent_name)

    @staticmethod
    def _make_remote(out: Dict[str, Any],
                     origin: str,
                     network_name: str,
                     agent_name: str) -> Dict[str, Any]:
        """Replace `class`/`toolbox` with a `coded_tool_url` pointing to origin."""
        out.pop("class", None)
        out.pop("toolbox", None)
        # Origin must not end with a trailing slash; URL is well-formed without one.
        clean_origin = origin.rstrip("/")
        out["coded_tool_url"] = (
            f"{clean_origin}/api/v1/{network_name}/tool/{agent_name}"
        )
        return out

    @staticmethod
    def _agent_name(agent_spec: Dict[str, Any]) -> str:
        """Extract the agent name from a spec (function.name preferred, then name)."""
        function_spec = agent_spec.get("function")
        if isinstance(function_spec, dict):
            name = function_spec.get("name")
            if isinstance(name, str) and name:
                return name
        name = agent_spec.get("name")
        if isinstance(name, str) and name:
            return name
        raise DistributableScrubberError(
            f"Agent spec is missing a name: {agent_spec!r}"
        )

    def _strip_secrets(self, llm_config: Dict[str, Any]) -> Dict[str, Any]:
        """Drop keys that look like server secrets (case-insensitive substring match)."""
        out: Dict[str, Any] = {}
        for key, value in llm_config.items():
            lower = key.lower()
            if any(pat in lower for pat in self.secret_patterns):
                continue
            if isinstance(value, dict):
                out[key] = self._strip_secrets(value)
            elif isinstance(value, list):
                out[key] = [
                    self._strip_secrets(item) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                out[key] = value
        return out

    def _load_class_source(self, class_ref: str) -> Tuple[bytes, str]:
        """
        Resolve the class file via the same path machinery the activation
        factory uses, then read its source bytes and compute SHA-256.

        :return: (source_bytes, integrity_string)
        """
        # Try the fully qualified form first.
        cls = self._resolve_class(class_ref)
        try:
            source_file = inspect.getsourcefile(cls)
        except TypeError as exc:
            raise DistributableScrubberError(
                f"Cannot locate source file for client_side tool {class_ref}: {exc}"
            ) from exc
        if not source_file:
            raise DistributableScrubberError(
                f"Cannot locate source file for client_side tool {class_ref}"
            )
        with open(source_file, "rb") as fh:
            source_bytes = fh.read()
        digest = hashlib.sha256(source_bytes).hexdigest()
        integrity = f"sha256-{digest}"
        return source_bytes, integrity

    def _resolve_class(self, class_ref: str):
        """Resolve a class ref like 'pkg.mod.Class' or short 'Class' to a real class."""
        # Try direct import first.
        if "." in class_ref:
            module_name, class_name = class_ref.rsplit(".", 1)
            try:
                module = importlib.import_module(module_name)
                return getattr(module, class_name)
            except (ImportError, AttributeError):
                pass

        # Fall back to leaf_common Resolver against AGENT_TOOL_PATH.
        parts = class_ref.split(".")
        class_name = parts[-1]
        module_path = ".".join(parts[:-1]) if len(parts) > 1 else class_name.lower()

        # Walk from most specific to most general, like AbstractClassActivation does.
        tool_path_parts = self.agent_tool_path.split(".")
        for i in range(len(tool_path_parts) + 1):
            current_path = ".".join(tool_path_parts[:len(tool_path_parts) - i])
            if not current_path:
                continue
            try:
                resolver = Resolver([current_path])
                cls = resolver.resolve_class_in_module(class_name, module_path)
                if cls is not None:
                    return cls
            except (ValueError, AttributeError, ImportError):
                continue

        raise DistributableScrubberError(
            f"Cannot resolve class {class_ref} from agent_tool_path={self.agent_tool_path}"
        )

    def _enforce_post_conditions(self, wire: Dict[str, Any]) -> None:
        """Verify nothing dangerous is leaking in the wire form."""
        # No commondefs.
        if "commondefs" in wire:
            raise DistributableScrubberError(
                "Scrubbed wire form still contains 'commondefs' — bug in scrubber."
            )

        # No class / toolbox remaining on any tool.
        for agent_spec in wire.get("tools", []) or []:
            if "class" in agent_spec:
                raise DistributableScrubberError(
                    f"Agent {agent_spec.get('name')!r} still has 'class' in wire form."
                )
            if "toolbox" in agent_spec:
                raise DistributableScrubberError(
                    f"Agent {agent_spec.get('name')!r} still has 'toolbox' in wire form."
                )

        # No obvious secrets in llm_config (and per-agent llm_config).
        self._assert_no_secrets(wire.get("llm_config"), where="top-level llm_config")
        for agent_spec in wire.get("tools", []) or []:
            self._assert_no_secrets(
                agent_spec.get("llm_config"),
                where=f"llm_config in agent {agent_spec.get('name')!r}",
            )

    def _assert_no_secrets(self, llm_config: Any, where: str) -> None:
        if not isinstance(llm_config, dict):
            return
        for key, value in llm_config.items():
            lower = key.lower()
            if any(pat in lower for pat in self.secret_patterns):
                raise DistributableScrubberError(
                    f"Secret-looking key {key!r} survived scrubbing in {where}."
                )
            if isinstance(value, dict):
                self._assert_no_secrets(value, where=f"{where}.{key}")
            elif isinstance(value, str):
                # Heuristic: very long hex-ish or sk-/AKIA-prefixed strings might be keys.
                if re.match(r"^(sk-[A-Za-z0-9_-]{20,}|AKIA[A-Z0-9]{16}|[A-Fa-f0-9]{40,})$", value):
                    raise DistributableScrubberError(
                        f"Value of {key!r} in {where} looks like a credential."
                    )
