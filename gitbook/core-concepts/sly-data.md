# Sly Data

**Sly data** is a mechanism for passing structured data between agents without exposing it
to the LLM. This is useful for transmitting information that should not influence the LLM's
reasoning or that contains sensitive content.

## Why Sly Data?

When agents communicate through normal text messages, those messages pass through the LLM.
This means:

- The LLM sees the data and may interpret it unpredictably
- Structured data (JSON, IDs, tokens) can get mangled by the LLM
- Sensitive data (user IDs, session tokens) is exposed to the model
- Large payloads waste tokens and slow down processing

Sly data solves these problems by providing a **side channel** that bypasses the LLM
entirely.

## How It Works

Sly data flows alongside regular messages through the agent network:

```
┌────────────────────────────────────────────────┐
│              Normal Channel (LLM)              │
│  User: "Book flight to NYC" ──────► Agent      │
├────────────────────────────────────────────────┤
│              Sly Data Channel                  │
│  {"user_id": "abc123", "auth": "..."} ──► Tool │
└────────────────────────────────────────────────┘
```

- Regular text messages go through the LLM for reasoning
- Sly data passes directly to CodedTools without LLM involvement
- Sly data **accumulates** as it moves through the network -- each agent can add to it

## Sending Sly Data from a Client

When interacting with the agent network, clients can attach sly data to their messages:

### Python Client

```python
from neuro_san.session.http_service_agent_session import HttpServiceAgentSession

session = HttpServiceAgentSession(base_url="http://localhost:8080")
session.agent_name = "my_agent"

response = session.chat(
    "Book a flight to NYC",
    sly_data={"user_id": "abc123", "preferences": {"class": "economy"}}
)
```

### curl

```bash
curl -X POST http://localhost:8080/streaming_chat \
    -H "Content-Type: application/json" \
    -d '{
        "agent": "my_agent",
        "text": "Book a flight to NYC",
        "sly_data": {"user_id": "abc123", "preferences": {"class": "economy"}}
    }'
```

## Accessing Sly Data in CodedTools

CodedTools can read and write sly data through the `sly_data` parameter:

```python
from neuro_san.interfaces.coded_tool import CodedTool


class FlightBooker(CodedTool):

    def invoke(self, args: dict, sly_data: dict) -> dict:
        user_id = sly_data.get("user_id")
        preferences = sly_data.get("preferences", {})

        booking = self._book_flight(
            user_id=user_id,
            destination=args.get("destination"),
            travel_class=preferences.get("class", "economy")
        )

        sly_data["booking_id"] = booking.id

        return {
            "response": f"Booked flight {booking.id} to {args['destination']}",
            "sly_data": sly_data
        }
```

Key points:

- `sly_data` arrives as a dictionary
- Read values with `sly_data.get("key")`
- Add values by setting keys on the dictionary
- Return the updated `sly_data` in the response

## Common Use Cases

| Use Case | What Goes in Sly Data |
|:---------|:---------------------|
| Authentication | User IDs, session tokens, auth headers |
| State management | Shopping cart contents, form data |
| File references | File paths, URLs, binary data references |
| Configuration | Feature flags, user preferences |
| Audit trails | Request IDs, timestamps, source info |

## Sly Data vs. Regular Messages

| | Regular Messages | Sly Data |
|:--|:----------------|:---------|
| Visible to LLM | Yes | No |
| Affects reasoning | Yes | No |
| Format | Text | Structured (dict) |
| Uses tokens | Yes | No |
| Accumulates | No | Yes |
| Available to CodedTools | Via args | Via sly\_data |

## Next Steps

- [Tools and CodedTools](tools.md) -- Learn how to write tools that use sly data
- [Clients Reference](../reference/clients.md) -- Client APIs for sending sly data
