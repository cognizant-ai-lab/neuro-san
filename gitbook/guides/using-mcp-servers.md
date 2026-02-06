# Using MCP Servers

**MCP (Model Context Protocol)** is an open protocol for connecting LLMs to external tools
and data sources. Neuro SAN supports MCP in two ways:

1. **As a consumer** -- Agents can use tools from external MCP servers
2. **As a provider** -- The Neuro SAN server exposes agent networks as MCP tools

## Connecting to External MCP Servers

### Inline Configuration

Define MCP servers directly in an agent's HOCON configuration:

```hocon
{
    "name": "file_manager",
    "function": {
        "description": "I help manage files on the filesystem."
    },
    "instructions": "Help users manage files using the available tools.",
    "mcp_servers": {
        "filesystem": {
            "command": "npx",
            "args": [
                "-y",
                "@modelcontextprotocol/server-filesystem",
                "/tmp/workspace"
            ]
        }
    }
}
```

The agent automatically discovers and can use all tools exposed by the MCP server.

### Remote MCP Servers

Connect to MCP servers running on remote hosts:

```hocon
{
    "name": "github_agent",
    "instructions": "Help users interact with GitHub repositories.",
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

### Shared MCP Configuration

For MCP servers used across multiple agents, define them in a separate file:

```hocon
# mcp_info.hocon
{
    "github": {
        "url": "https://mcp.github.com/v1",
        "transport": "streamable_http"
    },
    "slack": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-slack"]
    }
}
```

Reference with the environment variable:

```bash
export AGENT_MCP_INFO_FILE="path/to/mcp_info.hocon"
```

## Exposing Agent Networks as MCP Tools

Neuro SAN can serve your agent networks as MCP tools for other systems to consume.

### Enable MCP in the Manifest

Mark agent networks as MCP-enabled in `manifest.hocon`:

```hocon
{
    "my_agent.hocon": {
        "serve": true,
        "public": true,
        "mcp": true
    }
}
```

### The MCP Endpoint

When the server is running, the MCP endpoint is available at:

```
http://localhost:8080/mcp
```

The server implements the MCP protocol (version 2025-06-18) and supports:

- `initialize` -- Handshake and capability negotiation
- `tools/list` -- List available agent networks as tools
- `tools/call` -- Execute an agent network

### Example: Calling an MCP Tool

```bash
curl -X POST http://localhost:8080/mcp \
    -H "Content-Type: application/json" \
    -d '{
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list"
    }'
```

```bash
curl -X POST http://localhost:8080/mcp \
    -H "Content-Type: application/json" \
    -d '{
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "hello_world",
            "arguments": {
                "text": "Greet the planet Mars"
            }
        }
    }'
```

### Connecting from the CLI

Use the CLI client with MCP mode:

```bash
python -m neuro_san.client.agent_cli --mcp --agent hello_world
```

## Best Practices

1. **Use environment variable substitutions for credentials.** Never hardcode API tokens
   in MCP server configurations.
2. **Limit filesystem access.** When using filesystem MCP servers, scope access to specific
   directories.
3. **Test MCP connections independently.** Verify the MCP server works before integrating
   it into an agent network.

## Next Steps

- [MCP Service Reference](../reference/mcp-service.md) -- Complete MCP protocol details
- [External Agent Networks](external-agents.md) -- Connect agent networks across servers
