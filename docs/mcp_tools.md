# MCP Servers as Tools

Agents can call tools exposed by external Model Context Protocol (MCP) servers by listing the server in
their [`tools`](./agent_hocon_reference.md#tools-agents) list. This document covers that client side: how
a server is referenced, which of its tools the agent gets, what the LLM sees them as, and how to authenticate.

To serve your own agent networks as MCP tools, see [MCP Service](./mcp_service.md). To call another
neuro-san agent network directly, see [External Agents](./external_agents.md).

<!--TOC-->

- [Recognized server URLs](#recognized-server-urls)
- [String and dictionary references](#string-and-dictionary-references)
- [Tool names](#tool-names)
- [Authentication](#authentication)

<!--TOC-->

## Recognized server URLs

MCP server URLs are recognized when they conform to the
[MCP canonical server URI specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization#canonical-server-uri):
they must use the `http` or `https` scheme, must include a host, and must not contain a fragment.
To distinguish MCP server URLs from other external agent URLs, the literal `mcp` must appear either
as a label in the hostname (e.g. `mcp.example.com`) or as any segment of the URL path
(e.g. `/mcp`, `/mcp/free`, `/server/mcp`, `/v1/mcp/server`).

Examples of URLs that are recognized as MCP servers:

- `https://mcp.example.com/mcp`
- `https://mcp.example.com`
- `https://mcp.example.com:8443`
- `https://example.com/mcp/free`
- `https://example.com/v1/mcp/server`
- `http://localhost:8000/mcp/`

If a URL you want to use does not satisfy these rules, fall back to the dictionary form below,
which is always treated as an MCP reference regardless of URL shape.

## String and dictionary references

MCP servers can be configured in two formats:

- string reference

    ```json
    "tools": ["https://example.com/mcp"]
    ```

    - Tool filtering is not available with string reference format unless using environment variable
    `MCP_SERVERS_INFO_FILE` (see [Authentication](#authentication) below).

- dictionary reference

    ```json
    "tools": [
        {
            "url": "https://example.com/mcp",
            "tools": ["tool_1"]
        }
    ]
    ```

    - `tools` key filters which specific tools from the MCP server are made available.
    If omitted, all tools on the server will be accessible.
    - An entry that matches no tool on the server is reported to the client, and the server log also
    lists the names the server does offer. The other entries still take effect.

## Tool names

- Any tool name outside `^[a-zA-Z0-9_-]+$` is renamed before the LLM sees it, because OpenAI
and Anthropic reject such names and fail the whole request: "/" becomes "__" and any other
unsafe character becomes "_". The MCP server is still called with the original name. A current
neuro-san server already advertises its nested agent networks under provider-safe names,
`deep__math_guy` for the network `deep/math_guy` (see
[Agent networks as MCP tools](./mcp_service.md#agent-networks-as-mcp-tools)); a `deep/math_guy`
tool from an older neuro-san server is renamed here the same way, so the LLM sees
`deep__math_guy` either way. A name longer than 64 characters (OpenAI's cap) or 128 (Anthropic's),
renamed or not, is kept but warned about.
- Both spellings are accepted in the `tools` allow list, so `"tools": ["deep/math_guy"]` selects
the tool whether the server advertises it as `deep/math_guy` or as `deep__math_guy`. When a
server offers both spellings of one name, an entry selects the tool it spells exactly.
- Two tools on one server that end up with the same name, advertised twice or renamed alike, are a
collision: the tool that needed no rename (or, failing that, the first one listed) is kept and the
other is dropped with a warning. Across servers, and against the network's other tools, the first
tool in the agent's `tools` list to use a name keeps it; a later MCP tool with the same name is
skipped with a warning.
- Thinking output and journal entries show the renamed name, since that is the name the LLM uses.

## Authentication

MCP tools can be authenticated using the following methods:

- `http_headers` field in `sly_data`. The required fields depend on the authentication scheme expected by each MCP
server. Users may specify different authorization credentials for different MCP URLs.

    Example:

    ```json
    {
        "http_headers": {
            "<MCP_URL_1>": {
                "Authorization": "Bearer <token_value>"
            },
            "<MCP_URL_2>": {
                "client_id": "<client_id_value>",
                "client_secret": "<client_secret_value>"
            }
        }
    }
    ```

- Set the `MCP_SERVERS_INFO_FILE` environment variable to point to a HOCON file containing MCP server configurations:

    ```json
    {
        "mcp_server_url_1": {
            "http_headers": {
                "Authorization": "Bearer <token>",
            },
            "tools": ["tool_1", "tool_2"]
        },
    }
    ```

    - Server URLs must match those in the agent network HOCON file

    - If the headers exist in both `sly_data` and the configuration file for the same server,
    `sly_data` takes precedence

    - Tool filtering from the configuration file is used only if no tool filtering exists in the agent network HOCON

A client can also populate these `http_headers` on the user's behalf: see
[http_headers](./agent_hocon_reference.md#http_headers) under `sly_data_schema`, where a network advertises the
MCP URLs it needs and an OAuth-capable client (e.g. nsflow) signs in and injects the bearer token, gating on
`http_headers.required`.
