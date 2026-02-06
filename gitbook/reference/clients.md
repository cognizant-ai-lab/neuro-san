# Clients Reference

Neuro SAN provides multiple client interfaces for interacting with agent networks.

## Connection Modes

| Mode | Class | Protocol | Use Case |
|:-----|:------|:---------|:---------|
| Direct | `DirectAgentSession` | In-process | Development, testing |
| HTTP | `HttpServiceAgentSession` | REST/HTTP | Production, remote access |
| MCP | `McpServiceAgentSession` | MCP protocol | Integration with MCP clients |

## Python Client: DirectAgentSession

Runs the agent network in the same process. No server needed.

```python
from neuro_san.session.direct_agent_session import DirectAgentSession

session = DirectAgentSession()
session.agent_name = "hello_world"

for response in session.streaming_chat("Greet Mars"):
    if response.get("type") == "AGENT_FRAMEWORK":
        print(response.get("text", ""))
```

### Async Version

```python
from neuro_san.session.async_direct_agent_session import AsyncDirectAgentSession

session = AsyncDirectAgentSession()
session.agent_name = "hello_world"

async for response in session.streaming_chat("Greet Mars"):
    if response.get("type") == "AGENT_FRAMEWORK":
        print(response.get("text", ""))
```

## Python Client: HttpServiceAgentSession

Connects to a running Neuro SAN server over HTTP.

```python
from neuro_san.session.http_service_agent_session import HttpServiceAgentSession

session = HttpServiceAgentSession(base_url="http://localhost:8080")
session.agent_name = "hello_world"

for response in session.streaming_chat("Greet Mars"):
    if response.get("type") == "AGENT_FRAMEWORK":
        print(response.get("text", ""))
```

### With sly\_data

```python
response = session.streaming_chat(
    "Book a flight to NYC",
    sly_data={"user_id": "abc123", "auth_token": "..."}
)
```

### With chat\_context (Multi-Turn)

```python
chat_context = None

for response in session.streaming_chat("What's the weather?"):
    if response.get("type") == "AGENT_FRAMEWORK":
        chat_context = response.get("chat_context")

for response in session.streaming_chat("How about tomorrow?", chat_context=chat_context):
    ...
```

## Command-Line Client

The built-in CLI provides an interactive chat interface:

```bash
# Direct mode (no server)
python -m neuro_san.client.agent_cli --agent hello_world

# HTTP mode (connect to server)
python -m neuro_san.client.agent_cli --http --agent hello_world

# Custom host and port
python -m neuro_san.client.agent_cli --http --host remote.example.com --port 8080 --agent hello_world

# MCP mode
python -m neuro_san.client.agent_cli --mcp --agent hello_world
```

### CLI Flags

| Flag | Description |
|:-----|:------------|
| `--agent NAME` | Agent network name |
| `--http` | Use HTTP connection mode |
| `--https` | Use HTTPS connection mode |
| `--mcp` | Use MCP connection mode |
| `--host HOST` | Server hostname (default: `localhost`) |
| `--port PORT` | Server port (default: `8080`) |

## curl

### Get Agent Description

```bash
curl -X POST http://localhost:8080/function \
    -H "Content-Type: application/json" \
    -d '{"agent": "hello_world"}'
```

### Chat with an Agent

```bash
curl -X POST http://localhost:8080/streaming_chat \
    -H "Content-Type: application/json" \
    -d '{"agent": "hello_world", "text": "Greet Mars"}'
```

### Chat with sly\_data

```bash
curl -X POST http://localhost:8080/streaming_chat \
    -H "Content-Type: application/json" \
    -d '{
        "agent": "coffee_finder",
        "text": "Where can I get coffee?",
        "sly_data": {"time": "8 am"}
    }'
```

### Multi-Turn with chat\_context

```bash
# First request
RESPONSE=$(curl -s -X POST http://localhost:8080/streaming_chat \
    -H "Content-Type: application/json" \
    -d '{"agent": "my_agent", "text": "Hello"}')

# Extract chat_context
CONTEXT=$(echo "$RESPONSE" | jq -r '.chat_context')

# Second request with context
curl -X POST http://localhost:8080/streaming_chat \
    -H "Content-Type: application/json" \
    -d "{\"agent\": \"my_agent\", \"text\": \"Follow up\", \"chat_context\": $CONTEXT}"
```

## Response Format

All clients receive streaming responses. Each response message has a `type` field:

| Type | Description |
|:-----|:------------|
| `AI` | Intermediate agent message (reasoning, delegation) |
| `AGENT_FRAMEWORK` | Final response from the Front Man |

The final `AGENT_FRAMEWORK` message contains:

| Field | Description |
|:------|:------------|
| `text` | The agent's text response |
| `chat_context` | Serialized conversation state for multi-turn |
| `sly_data` | Returned sly\_data (if any) |
| `origin` | Message provenance chain |
