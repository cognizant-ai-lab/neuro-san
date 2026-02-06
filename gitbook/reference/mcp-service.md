# MCP Service Reference

Neuro SAN implements the **Model Context Protocol (MCP)** to expose agent networks as
tools that other MCP-compatible systems can consume.

## Protocol Version

Neuro SAN implements MCP protocol version **2025-06-18**.

## Endpoint

When the server is running, the MCP endpoint is available at:

```
http://localhost:8080/mcp
```

All requests use **JSON-RPC 2.0** format over HTTP POST.

## Supported Methods

### initialize

Handshake to establish a session.

**Request:**

```json
{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {
            "name": "my-client",
            "version": "1.0.0"
        }
    }
}
```

**Response:**

```json
{
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "protocolVersion": "2025-06-18",
        "capabilities": {
            "tools": {}
        },
        "serverInfo": {
            "name": "neuro-san",
            "version": "..."
        }
    }
}
```

### notifications/initialized

Notification to confirm initialization is complete.

```json
{
    "jsonrpc": "2.0",
    "method": "notifications/initialized"
}
```

### tools/list

List all agent networks available as MCP tools.

**Request:**

```json
{
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/list"
}
```

**Response:**

```json
{
    "jsonrpc": "2.0",
    "id": 2,
    "result": {
        "tools": [
            {
                "name": "hello_world",
                "description": "I can help you to make a terse announcement.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "text": {
                            "type": "string",
                            "description": "The user's message."
                        }
                    },
                    "required": ["text"]
                }
            }
        ]
    }
}
```

Only agent networks with `mcp: true` in the manifest are listed.

### tools/call

Execute an agent network as a tool.

**Request:**

```json
{
    "jsonrpc": "2.0",
    "id": 3,
    "method": "tools/call",
    "params": {
        "name": "hello_world",
        "arguments": {
            "text": "Greet the planet Mars."
        }
    }
}
```

**Response:**

```json
{
    "jsonrpc": "2.0",
    "id": 3,
    "result": {
        "content": [
            {
                "type": "text",
                "text": "Hello, Mars!"
            }
        ]
    }
}
```

### tools/call with sly\_data

Pass sly\_data alongside the tool call:

```json
{
    "jsonrpc": "2.0",
    "id": 4,
    "method": "tools/call",
    "params": {
        "name": "coffee_finder",
        "arguments": {
            "text": "Where can I get coffee?",
            "sly_data": {"time": "8 am"}
        }
    }
}
```

## Enabling MCP

### In the Manifest

```hocon
{
    "hello_world.hocon": {
        "serve": true,
        "public": true,
        "mcp": true
    }
}
```

### Server Configuration

The MCP endpoint is enabled automatically when the HTTP server starts. No additional
configuration is needed.

## Connecting as an MCP Client

### From the CLI

```bash
python -m neuro_san.client.agent_cli --mcp --agent hello_world
```

### From curl

```bash
# Initialize
curl -X POST http://localhost:8080/mcp \
    -H "Content-Type: application/json" \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}'

# Confirm initialization
curl -X POST http://localhost:8080/mcp \
    -H "Content-Type: application/json" \
    -d '{"jsonrpc":"2.0","method":"notifications/initialized"}'

# List tools
curl -X POST http://localhost:8080/mcp \
    -H "Content-Type: application/json" \
    -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}'

# Call a tool
curl -X POST http://localhost:8080/mcp \
    -H "Content-Type: application/json" \
    -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"hello_world","arguments":{"text":"Greet Mars"}}}'
```
