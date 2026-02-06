# Memory and Conversation

Neuro SAN supports multi-turn conversations where agents remember previous messages
within a session. This guide covers how conversation state works and how to maintain
context across interactions.

## How Conversation State Works

Each interaction with an agent network returns a `chat_context` object. This object
contains the serialized conversation history. To continue the conversation, pass it
back with the next request.

```
Request 1:  "What's the weather in NYC?"
Response 1: "It's 72°F and sunny." + chat_context

Request 2:  "How about tomorrow?" + chat_context
Response 2: "Tomorrow will be 68°F with clouds."
```

Without `chat_context`, each request starts a new conversation with no memory of
previous messages.

## Using chat\_context with the Python Client

```python
from neuro_san.session.http_service_agent_session import HttpServiceAgentSession

session = HttpServiceAgentSession(base_url="http://localhost:8080")
session.agent_name = "weather_assistant"

response1 = session.chat("What's the weather in NYC?")
print(response1["text"])

response2 = session.chat(
    "How about tomorrow?",
    chat_context=response1["chat_context"]
)
print(response2["text"])
```

## Using chat\_context with curl

```bash
RESPONSE=$(curl -s -X POST http://localhost:8080/streaming_chat \
    -H "Content-Type: application/json" \
    -d '{"agent": "weather_assistant", "text": "What is the weather in NYC?"}')

CHAT_CONTEXT=$(echo $RESPONSE | jq '.chat_context')

curl -X POST http://localhost:8080/streaming_chat \
    -H "Content-Type: application/json" \
    -d "{
        \"agent\": \"weather_assistant\",
        \"text\": \"How about tomorrow?\",
        \"chat_context\": $CHAT_CONTEXT
    }"
```

## What chat\_context Contains

The `chat_context` is an opaque dictionary containing:

- **Chat histories** -- The conversation messages for each agent in the network
- **State information** -- Agent instantiation indices and session metadata

You should treat `chat_context` as opaque data. Don't modify its contents -- just pass
it back as-is with each subsequent request.

## Session-Based Conversation (Direct Mode)

When using `DirectAgentSession` (in-process), conversation state is maintained
automatically within the session object:

```python
from neuro_san.session.direct_agent_session import DirectAgentSession

session = DirectAgentSession()
session.agent_name = "weather_assistant"

session.chat("What's the weather in NYC?")
session.chat("How about tomorrow?")
```

## Conversation Limits

- Each agent in the network maintains its own chat history
- Histories grow with each turn, consuming more tokens
- Very long conversations may hit the model's context window limit
- Consider starting fresh conversations for unrelated topics

## Next Steps

- [Sly Data](../core-concepts/sly-data.md) -- Pass structured data alongside conversations
- [Clients Reference](../reference/clients.md) -- Complete client API documentation
