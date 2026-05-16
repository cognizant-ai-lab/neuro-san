
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
Agent Web browser CLI.

Fetches a Jupyter notebook from an Agent Web /network endpoint, extracts the
scrubbed wire config, verifies integrity / same-origin invariants, builds an
in-memory AgentNetwork, and runs it as a chat against the local process.

LLM calls happen in this process using the local environment's API keys
(OPENAI_API_KEY etc.). Server-side coded tools at the origin are invoked
via RemoteToolActivation (POST /tool/). Client-side coded tools shipped in
the notebook are executed locally via ClientSideToolActivation.

When running with a JupyterLite-backed Pyodide kernel, this same code path
gives the runtime the wasm sandbox. When running as a Python CLI on a
trusted local machine, the integrity-checked source still executes with
full host privileges — this CLI is intended as a developer/test driver and
as the headless analogue of a JupyterLite extension, not as a public-facing
"browser" for untrusted networks.

Usage:
    python -m neuro_san.client.agent_web_browser \\
        --url http://localhost:8803/api/v1/trip_planner/network \\
        --message "SFO to Tokyo around June 14-21, hotel near Shinjuku..." \\
        --sly-data passenger_email=bob@example.com

See docs/agent_web_design.md (§6.3) for design details.
"""
import argparse
import asyncio
import contextlib
import json
import logging
import sys
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from urllib.parse import urlparse

import aiohttp

from leaf_common.asyncio.asyncio_executor_pool import AsyncioExecutorPool

from neuro_san.client.direct_agent_storage_util import DirectAgentStorageUtil  # noqa: F401
from neuro_san.internals.distribution.agent_web_notebook import (
    extract_wire_config_from_notebook,
)
from neuro_san.internals.distribution.distributable_network_scrubber import (
    AGENT_WEB_PROTOCOL_VERSION,
)
from neuro_san.internals.graph.persistence.agent_network_restorer import AgentNetworkRestorer
from neuro_san.internals.graph.registry.agent_network import AgentNetwork
from neuro_san.internals.interfaces.context_type_llm_factory import ContextTypeLlmFactory
from neuro_san.internals.interfaces.context_type_toolbox_factory import ContextTypeToolboxFactory
from neuro_san.internals.interfaces.storage_class import StorageClass
from neuro_san.internals.network_providers.agent_network_storage import AgentNetworkStorage
from neuro_san.internals.network_providers.expiring_agent_network_storage import (
    ExpiringAgentNetworkStorage,
)
from neuro_san.internals.reservations.direct_agent_reservationist import (
    DirectAgentReservationist,
)
from neuro_san.internals.run_context.factory.master_llm_factory import MasterLlmFactory
from neuro_san.internals.run_context.factory.master_toolbox_factory import (
    MasterToolboxFactory,
)
from neuro_san.message_processing.basic_message_processor import BasicMessageProcessor
from neuro_san.session.async_direct_agent_session import AsyncDirectAgentSession
from neuro_san.session.external_agent_session_factory import ExternalAgentSessionFactory
from neuro_san.session.session_invocation_context import SessionInvocationContext


# ---- protocol-level helpers ----------------------------------------------


def fetch_notebook(url: str, timeout_seconds: float = 30.0) -> Dict[str, Any]:
    """Synchronous fetch of an Agent Web notebook from `url`."""
    return asyncio.run(_async_fetch_notebook(url, timeout_seconds))


async def _async_fetch_notebook(url: str, timeout_seconds: float) -> Dict[str, Any]:
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as response:
            if response.status != 200:
                body = await response.text()
                raise ValueError(
                    f"Failed to fetch notebook from {url}: HTTP {response.status}: {body[:300]}"
                )
            return await response.json(content_type=None)


def verify_wire_config(wire: Dict[str, Any]) -> None:
    """
    Enforce the runtime-side invariants on a fetched wire config:
      - protocol_version matches what this runtime supports.
      - every coded_tool_url is same-origin with the notebook's stamped origin.
      - every client-side tool has client_side_source and integrity fields.
      - no `class` / `toolbox` remain (the scrubber should have stripped them).
    """
    meta: Dict[str, Any] = wire.get("agent_web") or {}
    proto: Optional[str] = meta.get("protocol_version")
    origin: Optional[str] = meta.get("origin")

    if proto != AGENT_WEB_PROTOCOL_VERSION:
        raise ValueError(
            f"Agent Web protocol version mismatch: notebook is {proto!r}, "
            f"runtime supports {AGENT_WEB_PROTOCOL_VERSION!r}. Refusing to load."
        )
    if not origin:
        raise ValueError("Notebook missing agent_web.origin metadata; refusing to load.")

    origin_parsed = urlparse(origin)
    origin_netloc = origin_parsed.netloc

    for agent_spec in wire.get("tools", []) or []:
        if "class" in agent_spec:
            raise ValueError(
                f"Refusing to load: tool {agent_spec.get('name')!r} still has 'class' "
                "in the wire form. Origin's scrubber is misconfigured."
            )
        if "toolbox" in agent_spec:
            raise ValueError(
                f"Refusing to load: tool {agent_spec.get('name')!r} still has 'toolbox'."
            )
        coded_tool_url = agent_spec.get("coded_tool_url")
        if coded_tool_url:
            tool_parsed = urlparse(coded_tool_url)
            if tool_parsed.netloc != origin_netloc:
                raise ValueError(
                    f"Refusing to load: tool {agent_spec.get('name')!r} has "
                    f"coded_tool_url={coded_tool_url!r} which is not same-origin "
                    f"with the notebook origin {origin!r}."
                )
        if agent_spec.get("client_side"):
            if not agent_spec.get("client_side_source"):
                raise ValueError(
                    f"Refusing to load: client_side tool {agent_spec.get('name')!r} "
                    "is missing client_side_source."
                )
            if not agent_spec.get("integrity"):
                raise ValueError(
                    f"Refusing to load: client_side tool {agent_spec.get('name')!r} "
                    "is missing integrity hash."
                )


def build_agent_network_from_wire(wire: Dict[str, Any]) -> AgentNetwork:
    """Build an in-memory AgentNetwork from a verified wire config."""
    network_name: str = (wire.get("agent_web") or {}).get("network_name") or "agent_web_network"
    # Run the standard filter chain so defaults/name corrections apply, but
    # against the already-resolved wire config. (commondefs is absent.)
    restorer = AgentNetworkRestorer()
    filtered: Dict[str, Any] = restorer.filter_config(wire)
    return AgentNetwork(filtered, network_name)


# ---- session orchestration -----------------------------------------------


def open_agent_from_notebook(notebook: Optional[Dict[str, Any]] = None,
                             url: Optional[str] = None,
                             initial_message: Optional[str] = None,
                             sly_data: Optional[Dict[str, Any]] = None,
                             interactive: bool = True,
                             inactivity_timeout: float = 120.0) -> None:
    """
    Public helper invoked by the notebook's kickoff cell.

    :param notebook: An already-parsed notebook dict. When None, `url` is fetched.
    :param url: Alternative to `notebook`: a URL to fetch.
    :param initial_message: An optional first user message. If None and interactive
            is True, the helper reads from stdin in a chat loop.
    :param sly_data: Optional starting sly_data to thread into the network.
    :param interactive: If True, runs an stdin chat loop. If False, only the
            initial_message is sent and the answer is printed once.
    """
    if notebook is None:
        if not url:
            raise ValueError("open_agent_from_notebook needs either notebook or url")
        notebook = fetch_notebook(url)

    wire: Dict[str, Any] = extract_wire_config_from_notebook(notebook)
    verify_wire_config(wire)

    sly_data = dict(sly_data or {})
    asyncio.run(_run_session(wire, initial_message, sly_data, interactive,
                             inactivity_timeout=inactivity_timeout))


async def _run_session(wire: Dict[str, Any],
                       initial_message: Optional[str],
                       sly_data: Dict[str, Any],
                       interactive: bool,
                       inactivity_timeout: float = 120.0) -> None:
    """Build the network, set up the invocation context, and run a chat loop."""
    agent_network = build_agent_network_from_wire(wire)

    # Tiny single-network storage just for the lifetime of this session.
    network_storage = AgentNetworkStorage()
    network_storage.add_agent_network(agent_network.get_network_name(), agent_network)
    network_storage_dict: Dict[str, AgentNetworkStorage] = {
        StorageClass.PUBLIC: network_storage,
        StorageClass.TEMP: ExpiringAgentNetworkStorage(),
    }

    config: Dict[str, Any] = agent_network.get_config()
    llm_factory: ContextTypeLlmFactory = MasterLlmFactory.create_llm_factory(config)
    toolbox_factory: ContextTypeToolboxFactory = MasterToolboxFactory.create_toolbox_factory(config)
    llm_factory.load()
    toolbox_factory.load()

    external_factory = ExternalAgentSessionFactory(
        use_direct=False, network_storage_dict=network_storage_dict
    )
    executors_pool = AsyncioExecutorPool()
    reservationist = DirectAgentReservationist(
        {network_storage_dict[StorageClass.TEMP]}
    )

    invocation_context = SessionInvocationContext(
        agent_network.get_network_name(),
        external_factory,
        executors_pool,
        llm_factory,
        toolbox_factory,
        None,  # metadata
        reservationist,
    )
    invocation_context.start()

    try:
        session = AsyncDirectAgentSession(
            agent_network=agent_network,
            invocation_context=invocation_context,
        )

        chat_context: Dict[str, Any] = {}
        current_sly: Dict[str, Any] = dict(sly_data)

        async def turn(user_message: str) -> str:
            nonlocal chat_context, current_sly
            request: Dict[str, Any] = {
                "user_message": {"type": "HUMAN", "text": user_message},
            }
            if chat_context:
                request["chat_context"] = chat_context
            if current_sly:
                request["sly_data"] = current_sly

            processor = BasicMessageProcessor()
            # AsyncDirectAgentSession submits the real chat work to a
            # separate AsyncioExecutor thread. If that work fails or hangs,
            # the leaf_common executor either silently logs the exception or
            # holds the thread, and never puts a final marker on the queue —
            # so a naive `async for` over the stream would hang forever.
            # Defend with two mechanisms:
            #   1) An inactivity watchdog: abort if no message arrives in
            #      `inactivity_timeout` seconds.
            #   2) Surface the warning prominently so the user knows the LLM
            #      call hasn't produced anything and can check its logs.
            stream_iter = session.streaming_chat(request).__aiter__()

            # One persistent pending task per stream step. Async generators
            # don't allow concurrent __anext__ calls, so we keep the same task
            # across loop iterations until it resolves.
            next_task: Optional[asyncio.Task] = None
            elapsed_no_progress: float = 0.0
            poll_interval: float = 2.0
            try:
                while True:
                    if next_task is None:
                        next_task = asyncio.ensure_future(stream_iter.__anext__())

                    done, _ = await asyncio.wait(
                        {next_task}, timeout=poll_interval
                    )
                    if next_task in done:
                        elapsed_no_progress = 0.0
                        try:
                            chat_response = next_task.result()
                        except StopAsyncIteration:
                            break
                        next_task = None
                        response = chat_response.get("response", {}) or {}
                        await processor.async_process_message(response)
                        continue

                    elapsed_no_progress += poll_interval
                    if elapsed_no_progress >= inactivity_timeout:
                        raise RuntimeError(
                            f"Agent has produced no output for "
                            f"{inactivity_timeout:.0f}s — the LLM call has "
                            f"likely failed or is hung. Check the runtime log "
                            f"for exceptions (set --log-level INFO; common "
                            f"causes: bad API key, unreachable provider URL, "
                            f"or wrong model name)."
                        )
                    # No message yet; loop and keep waiting.
            finally:
                if next_task is not None and not next_task.done():
                    next_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError, Exception):
                        await next_task
            answer: str = processor.get_compiled_answer() or ""
            new_ctx = processor.get_chat_context()
            if new_ctx:
                chat_context = new_ctx
            returned_sly = processor.get_sly_data() or {}
            # Returned sly_data has already been redacted by allow.to_upstream
            # rules at the front-man boundary; merge it into our running state.
            current_sly.update(returned_sly)
            return answer

        if initial_message:
            print(f"\n[user]   {initial_message}", flush=True)
            answer = await turn(initial_message)
            print(f"[agent]  {answer}\n", flush=True)
            if current_sly:
                print(f"[sly_data] {json.dumps(current_sly)}\n", flush=True)

        if interactive:
            print("Type your messages (Ctrl-D to end):", flush=True)
            loop = asyncio.get_event_loop()
            while True:
                line = await loop.run_in_executor(None, sys.stdin.readline)
                if not line:
                    break
                user_message = line.strip()
                if not user_message:
                    continue
                answer = await turn(user_message)
                print(f"[agent]  {answer}\n", flush=True)
                if current_sly:
                    print(f"[sly_data] {json.dumps(current_sly)}\n", flush=True)

    finally:
        await invocation_context.close_of_request()


# ---- CLI entry point -----------------------------------------------------


def _parse_sly_data(items: List[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for item in items or []:
        if "=" not in item:
            raise ValueError(f"--sly-data must be key=value, got: {item!r}")
        key, value = item.split("=", 1)
        out[key.strip()] = value.strip()
    return out


def main(argv: Optional[List[str]] = None) -> int:
    # Surface logger messages from leaf_common's AsyncioExecutor that would
    # otherwise be invisible. The executor logs swallowed exceptions at INFO,
    # so we set the bar there.  Users can quieten with `--log-level WARNING`.
    parser = argparse.ArgumentParser(
        description="Agent Web browser: fetch a notebook URL and chat with the agent."
    )
    parser.add_argument(
        "--url",
        required=True,
        help="Full URL to an Agent Web /network endpoint, e.g. http://localhost:8803/api/v1/trip_planner/network",
    )
    parser.add_argument(
        "--message",
        "-m",
        default=None,
        help="One-shot user message. If omitted, falls into interactive mode.",
    )
    parser.add_argument(
        "--sly-data",
        action="append",
        default=[],
        help="Initial sly_data as key=value (repeatable).",
    )
    parser.add_argument(
        "--no-interactive",
        action="store_true",
        help="Do not enter interactive mode after the initial message.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        help="Python logging level for the runtime (default INFO so executor "
             "exceptions surface). Set to WARNING for quieter output.",
    )
    parser.add_argument(
        "--inactivity-timeout",
        type=float,
        default=120.0,
        help="Seconds to wait for the agent to produce its next message "
             "before aborting (default 120s). Most often a shorter value "
             "of 30-60s surfaces a stuck LLM call faster.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,    # override anything langchain/anthropic set up at import
    )

    sly_data: Dict[str, Any] = _parse_sly_data(args.sly_data)
    interactive: bool = not args.no_interactive and (args.message is None or sys.stdin.isatty())

    try:
        open_agent_from_notebook(
            url=args.url,
            initial_message=args.message,
            sly_data=sly_data,
            interactive=interactive,
            inactivity_timeout=args.inactivity_timeout,
        )
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
