
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

from typing import Any
from typing import Dict
from typing import List
from typing import Optional
from typing import Set

from copy import copy
from logging import Logger
from logging import getLogger
from threading import Lock

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from neuro_san.internals.run_context.langchain.mcp.mcp_servers_info_restorer import McpServersInfoRestorer
from neuro_san.internals.run_context.langchain.mcp.mcp_tool_error_handler import McpToolErrorHandler
from neuro_san.internals.utils.mcp_tool_name_policy import McpToolNamePolicy


class LangChainMcpAdapter:
    """
    Adapter class to fetch tools from a Multi-Client Protocol (MCP) server and return them as
    LangChain-compatible tools. This class provides static methods for interacting with MCP servers.

    Tool names are made provider-safe on the way in. OpenAI and Anthropic reject
    a whole request when any tool name falls outside ^[a-zA-Z0-9_-]+$, so a
    server tool such as "basic/music_nerd_pro" is exposed to the LLM as
    "basic__music_nerd_pro" via McpToolNamePolicy.filter(). Only the
    LangChain-side name changes: langchain_mcp_adapters builds each tool's
    coroutine as a closure over the original mcp.types.Tool and calls the server
    with that object's name, so the server never sees the renamed spelling.
    Allow-list entries may be written in either spelling; when a server offers
    both spellings of one name, an entry selects the tool it spells exactly.
    Two tools on one server that would end up with the same name, advertised
    twice or renamed alike, are a collision; the tool that needed no rename (or, failing that, the first one
    listed) is kept and the other is skipped with a warning. Tools from
    different servers are not compared, as before: LangChain dispatches by
    name, so two servers offering the same name shadow each other whether or
    not a rename produced it. Thinking output and journal entries show the
    renamed spelling because they read the LangChain tool name.
    A current neuro-san server already advertises its networks under
    provider-safe names (see McpToolsProcessor), so its tools normally pass
    through unchanged; the rename here covers other MCP servers and older
    neuro-san servers.
    """

    _mcp_info_lock: Lock = Lock()
    _mcp_servers_info: Dict[str, Any] = None

    def __init__(self):
        """
        Constructor
        """
        self.client_allowed_tools: List[str] = []
        self.logger: Logger = getLogger(self.__class__.__name__)
        # Maps server tool names to provider-safe ones and matches allow-list
        # entries in either spelling; built once per adapter.
        self.tool_name_policy: McpToolNamePolicy = McpToolNamePolicy()
        # Allow-list entries the last get_mcp_tools() call could not match to any
        # tool the server advertised, in either spelling. BaseToolFactory reports
        # these to the user; comparing the entries with the renamed tools instead
        # would flag "deep/math_guy" as missing after it was exposed as
        # "deep__math_guy".
        self.unmatched_allowed_tools: List[str] = []

    def _load_mcp_servers_info(self):
        """
        Loads MCP servers information from a configuration file if not already loaded.
        """
        # Write through the class so the cache stays shared across instances.
        # `self._mcp_servers_info = ...` would create an instance attribute that shadows
        # the class attribute, leaving the class-level cache stuck at None and causing
        # every new LangChainMcpAdapter to reload (and re-log) the config.
        with LangChainMcpAdapter._mcp_info_lock:
            if LangChainMcpAdapter._mcp_servers_info is None:
                try:
                    LangChainMcpAdapter._mcp_servers_info = McpServersInfoRestorer().restore()
                except ValueError as value_error:
                    self.logger.warning("Error occurred while loading MCP servers info: %s", value_error)
                    self.logger.info("Proceeding with empty MCP servers info.")
                if LangChainMcpAdapter._mcp_servers_info is None:
                    # Something went wrong reading the file.
                    # Prevent further attempts to load info.
                    LangChainMcpAdapter._mcp_servers_info = {}

    async def get_mcp_tools(
            self,
            server_url: str,
            allowed_tools: Optional[List[str]] = None,
            headers: Optional[Dict[str, Any]] = None
    ) -> List[BaseTool]:
        """
        Fetches tools from the given MCP server and returns them as a list of LangChain-compatible tools.

        Tools are filtered by the allow list first (matching against the server's
        original names), then renamed with McpToolNamePolicy.filter() so the
        names the LLM sees are accepted by OpenAI and Anthropic. A tool whose
        exposed name would duplicate another tool's from the same server is
        skipped with a warning, and a name longer than the 64-character OpenAI
        cap (or the 128-character Anthropic cap), renamed or not, is kept but
        warned about. A tool advertised without a name is skipped, and allow-list
        entries that are not non-empty strings are ignored, each with a warning.

        :param server_url: URL of the MCP server, e.g. https://mcp.deepwiki.com/mcp or http://localhost:8000/mcp/
        :param allowed_tools: Optional list of tool names to filter from the server's available tools.
                              Entries may use either the server's original spelling
                              (e.g. "basic/music_nerd_pro") or the provider-safe spelling
                              (e.g. "basic__music_nerd_pro"). If None, the "tools" list from
                              the MCP servers info for this server is used; if that is also
                              absent or empty, all tools from the server will be returned.
        :param headers: Optional dictionary of HTTP headers to include in the MCP requests.
        :return: A list of LangChain BaseTool instances retrieved from the MCP server,
                 with provider-safe names.
        """
        if self._mcp_servers_info is None:
            self._load_mcp_servers_info()

        mcp_tool_dict: Dict[str, Any] = {
            "url": server_url,
            "transport": "streamable_http",
        }
        # Try to look up authentication details first from the sly data then from the MCP servers info.
        headers_dict: Dict[str, Any] = headers or self._mcp_servers_info.get(server_url, {}).get("http_headers")
        if headers_dict:
            if isinstance(headers_dict, dict):
                # Use a copy to avoid modifying the original headers dictionary.
                mcp_tool_dict["headers"] = copy(headers_dict)
            else:
                self.logger.error("MCP client headers for server %s must be a dictionary.",  server_url)

        client = MultiServerMCPClient(
            {"server": mcp_tool_dict}
        )

        # The get_tools() method returns a list of StructuredTool instances, which are subclasses of BaseTool.
        # Internally, it calls load_mcp_tools(), which uses an `async with create_session(...)` block.
        # This guarantees that any temporary MCP session created is properly closed when the block exits,
        # even if an error is raised during tool loading.
        # See: https://github.com/langchain-ai/langchain-mcp-adapters/blob/main/langchain_mcp_adapters/tools.py#L164
        # Optimization:
        #   It's possible we might want to cache these results somehow to minimize tool calls.
        mcp_tools: List[BaseTool] = await client.get_tools()

        # If allowed_tools is provided, filter the list to include only those tools.
        client_allowed_tools: List[str] = allowed_tools
        if client_allowed_tools is None:
            # Check if MCP server info has a "tools" field to use as allowed tools.
            client_allowed_tools = self._mcp_servers_info.get(server_url, {}).get("tools", [])
        self.client_allowed_tools = client_allowed_tools

        # Filter before renaming so the allow list is matched against the names
        # the server actually advertised; McpToolNamePolicy.select_allowed()
        # takes care of accepting the provider-safe spelling as well.
        mcp_tools = self._filter_allowed_tools(server_url, mcp_tools, client_allowed_tools)
        mcp_tools = self._rename_tools_for_providers(server_url, mcp_tools)

        for tool in mcp_tools:
            # Add "langchain_tool" tags so journal callback can idenitify it.
            # These MCP tools are treated as Langchain tools and can be reported in the thinking file.
            tool.tags = ["langchain_tool"]
            # Not all BaseTool subclasses have a coroutine to wrap, but the
            # StructuredTools from langchain-mcp-adapters do: their async
            # implementation (the function that opens the MCP session and calls
            # the server) is held in their "coroutine" attribute.
            if getattr(tool, "coroutine", None) is not None:
                # Swap that attribute for a McpToolErrorHandler's async_invoke
                # bound method so that MCP call failures come back to the LLM as
                # concise "Error: ..." tool output instead of raw exceptions
                # that abort the whole agent chain. The handler captures the
                # original coroutine at construction, which is why it must be
                # created before the assignment overwrites the attribute. It
                # must be a bound method (not the handler instance itself) so
                # langgraph can pass it to typing.get_type_hints() during agent
                # construction. See McpToolErrorHandler for details.
                tool.coroutine = McpToolErrorHandler(tool).async_invoke

        return mcp_tools

    def _filter_allowed_tools(
            self,
            server_url: str,
            mcp_tools: List[BaseTool],
            client_allowed_tools: Optional[List[str]]
    ) -> List[BaseTool]:
        """
        Keeps only the tools permitted by the allow list, warning about entries
        that match nothing the server advertised and recording them in
        unmatched_allowed_tools.

        :param server_url: URL of the MCP server the tools came from, for log messages.
        :param mcp_tools: All tools returned by the server, still carrying their original names.
        :param client_allowed_tools: Allow-list entries in either the original or the
                                     provider-safe spelling. None or empty means no filtering;
                                     entries that are not non-empty strings are ignored with
                                     a warning.
        :return: The tools some allow-list entry resolves to, each entry choosing the
                 tool it spells exactly when the server offers both spellings and the
                 provider-safe equivalent otherwise, in server order; mcp_tools itself
                 when there is no allow list.
        """
        # An empty or absent allow list has always meant "take everything".
        self.unmatched_allowed_tools = []
        if not client_allowed_tools:
            return mcp_tools

        # The policy mangles each entry with a string filter, so anything that
        # is not a non-empty string is set aside with a warning rather than
        # raising inside the matching. Before renaming existed such an entry was
        # simply never equal to a tool name.
        usable_entries: List[str] = []
        invalid_entries: List[Any] = []
        for entry in client_allowed_tools:
            if isinstance(entry, str) and entry:
                usable_entries.append(entry)
            else:
                invalid_entries.append(entry)
        if invalid_entries:
            self.logger.warning(
                "MCP server %s: allow-list entries %s are not non-empty strings; ignoring them.",
                server_url, invalid_entries)

        original_names: List[str] = []
        for tool in mcp_tools:
            original_names.append(tool.name)

        # Entries that match nothing used to be dropped silently, leaving the
        # hocon author guessing why a tool never appeared. Log what the server
        # actually offers so a typo or an upstream rename is visible.
        unmatched: List[str] = self.tool_name_policy.find_unmatched(usable_entries, original_names)
        self.unmatched_allowed_tools = unmatched
        if unmatched:
            self.logger.warning(
                "MCP server %s: allow-list entries %s match no tool on the server. Available tools: %s",
                server_url, unmatched, original_names)

        # Each entry resolves to one advertised tool, exact spelling first, so an
        # allow list naming "a/b" does not also pull in a literal "a__b" the
        # server happens to offer, which the rename step would otherwise have to
        # choose between (and would choose the one the author did not name).
        selected: List[str] = self.tool_name_policy.select_allowed(usable_entries, original_names)

        filtered_tools: List[BaseTool] = []
        for tool in mcp_tools:
            if tool.name in selected:
                filtered_tools.append(tool)

        return filtered_tools

    def _collect_safe_names(self, mcp_tools: List[BaseTool]) -> Set[str]:
        """
        Collects the names of the tools that are already provider-safe and so
        will not be renamed.

        :param mcp_tools: The tools to inspect, carrying their original names.
        :return: The set of tool names that McpToolNamePolicy.filter() leaves unchanged.
        """
        safe_names: Set[str] = set()
        for tool in mcp_tools:
            # A missing name is skipped later, so it must not reserve anything.
            if tool.name and self.tool_name_policy.filter(tool.name) == tool.name:
                safe_names.add(tool.name)
        return safe_names

    def _rename_tools_for_providers(self, server_url: str, mcp_tools: List[BaseTool]) -> List[BaseTool]:
        """
        Renames tools whose names LLM providers would reject, skipping any whose
        exposed name would duplicate another tool's from the same server, and
        warning about names over a provider's length cap.

        Only the LangChain tool's name is changed. The coroutine built by
        langchain_mcp_adapters closes over the original mcp.types.Tool and keeps
        calling the server with the original name.

        :param server_url: URL of the MCP server the tools came from, for log messages.
        :param mcp_tools: The tools to rename, already filtered by the allow list.
        :return: The tools to expose to the LLM, in server order, with provider-safe names.
        """
        # Seed with the names that need no rename so that a tool literally named
        # "a__b" always beats a tool "a/b" that would be renamed to the same
        # thing, whichever order the server listed them in.
        taken_names: Set[str] = self._collect_safe_names(mcp_tools)
        # Names exposed so far. A server that advertises one already-safe name
        # twice is a collision as well: the first tool is kept and the duplicate
        # skipped, so the LLM never sees two tools under one name.
        kept_names: Set[str] = set()

        kept_tools: List[BaseTool] = []
        for tool in mcp_tools:
            if not tool.name:
                # No LLM can call a nameless tool, and filter() would pass the
                # empty name straight through to a misleading length warning.
                self.logger.warning(
                    "MCP server %s: a tool is advertised without a name; skipping it.", server_url)
                continue

            safe_name: str = self.tool_name_policy.filter(tool.name)
            if safe_name == tool.name:
                if safe_name in kept_names:
                    self.logger.warning(
                        "MCP server %s: tool '%s' is advertised more than once; keeping the first "
                        "and skipping the duplicate.",
                        server_url, safe_name)
                    continue
            elif safe_name in taken_names:
                # Exposing two tools under one name would make the LLM's choice
                # ambiguous, so the later arrival is dropped rather than exposed.
                self.logger.warning(
                    "MCP server %s: tool '%s' would be renamed to '%s', which another tool on the same "
                    "server already uses; skipping it.",
                    server_url, tool.name, safe_name)
                continue
            else:
                taken_names.add(safe_name)
                # Expected, per-run housekeeping: create_mcp_tool() builds a fresh
                # adapter on every agent run, so this would spam WARNING otherwise.
                self.logger.info(
                    "MCP server %s: tool '%s' renamed to '%s' for LLM tool-name compatibility; "
                    "the server is still called with the original name",
                    server_url, tool.name, safe_name)
                tool.name = safe_name

            # Checked for every exposed name: a server can advertise an over-long
            # name that needs no rename, and "__" being longer than "/" can push
            # a renamed one over a cap.
            self._warn_if_too_long(server_url, safe_name)
            kept_names.add(safe_name)
            kept_tools.append(tool)

        return kept_tools

    def _warn_if_too_long(self, server_url: str, name: str) -> None:
        """
        Logs a warning when an exposed tool name exceeds a provider's length cap.
        The tool is kept either way, as the server side does, because lenient
        local providers accept such names.

        :param server_url: URL of the MCP server the tool came from, for log messages.
        :param name: The provider-safe name the LLM will see.
        """
        if not McpToolNamePolicy.is_valid_tool_name(name):
            # The characters are safe by now, so only the 128-character cap in
            # TOOL_NAME_PATTERN can fail here.
            self.logger.warning(
                "MCP server %s: tool name '%s' is %d characters long, over the 128-character "
                "tool-name cap that Anthropic enforces (OpenAI's is %d); requests that include it "
                "will fail on those providers.",
                server_url, name, len(name), McpToolNamePolicy.SOFT_MAX_LENGTH)
        elif self.tool_name_policy.is_over_soft_limit(name):
            self.logger.warning(
                "MCP server %s: tool name '%s' is %d characters long, over the %d-character "
                "OpenAI tool-name cap; OpenAI models may reject requests that include it.",
                server_url, name, len(name), McpToolNamePolicy.SOFT_MAX_LENGTH)
