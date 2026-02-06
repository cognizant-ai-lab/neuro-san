# MCP Integration

The **Model Context Protocol (MCP)** is an open standard for connecting LLMs to external
tools and data sources. Neuro SAN supports MCP as both a consumer and provider.

## Neuro SAN as an MCP Consumer

Agents can use tools from external MCP servers. This is useful for integrating with
third-party services that expose MCP endpoints.

### Configuration

Define MCP servers in an agent's HOCON configuration:

```hocon
{
    "name": "github_helper",
    "instructions": "Help users manage their GitHub repositories.",
    "mcp_servers": {
        "github": {
            "url": "https://mcp.github.com/v1",
            "transport": "streamable_http",
            "http_headers": {
                "Authorization": "Bearer ${GITHUB_TOKEN}"
            }
        }
    }
}
```

### Local MCP Servers

Run MCP servers locally:

```hocon
"mcp_servers": {
    "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    }
}
```

### Shared MCP Configuration

Define servers once and share across agents:

```bash
export AGENT_MCP_INFO_FILE="mcp/mcp_info.hocon"
```

## Neuro SAN as an MCP Provider

The Neuro SAN server exposes agent networks as MCP tools at the `/mcp` endpoint.

### Enable MCP

In the manifest:

```hocon
{
    "hello_world.hocon": {
        "serve": true,
        "public": true,
        "mcp": true
    }
}
```

### Protocol Details

- **Protocol version:** 2025-06-18
- **Transport:** HTTP POST with JSON-RPC 2.0
- **Endpoint:** `http://localhost:8080/mcp`
- **Supported methods:** `initialize`, `notifications/initialized`, `tools/list`,
  `tools/call`

See [MCP Service Reference](../reference/mcp-service.md) for the complete specification.

## Next Steps

- [Using MCP Servers](../guides/using-mcp-servers.md) -- Step-by-step guide
- [MCP Service Reference](../reference/mcp-service.md) -- Complete protocol reference
