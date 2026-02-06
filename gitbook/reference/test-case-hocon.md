# Test Case HOCON Reference

Data-driven test cases are defined in HOCON files that specify how to test an agent network
automatically. The framework runs the interactions and validates responses.

## File Location

Test case HOCON files are stored in `tests/fixtures/` and organized by category:

```
tests/fixtures/
├── basic/
│   ├── hello_world/
│   │   └── test_hello_world.hocon
│   └── music_nerd/
│       └── test_music_nerd.hocon
├── tools/
├── industry/
└── experimental/
```

## Format

```hocon
{
    "agent": "basic/hello_world",
    "connections": ["direct"],
    "timeout_in_seconds": 120,
    "success_ratio": "1/1",
    "interactions": [
        {
            "text": "Greet the planet Mars.",
            "response": {
                "text": {
                    "gist": ["The response contains a greeting to Mars."]
                }
            }
        }
    ]
}
```

## Top-Level Fields

| Field | Type | Required | Description |
|:------|:-----|:---------|:------------|
| `agent` | string | Yes | Agent network name (e.g., `"basic/hello_world"`) |
| `connections` | array | No | Connection types: `"direct"`, `"server"` |
| `timeout_in_seconds` | integer | No | Max time per interaction (default: 120) |
| `success_ratio` | string | No | Pass threshold as `"passes/total"` (default: `"1/1"`) |
| `use_direct` | boolean | No | Use direct mode instead of server (default: varies) |
| `interactions` | array | Yes | List of test interactions |

### success\_ratio

Accounts for LLM non-determinism. Format: `"passes/total_runs"`.

- `"1/1"` -- Must pass every time (100%)
- `"4/5"` -- Must pass 4 out of 5 runs (80%)
- `"2/3"` -- Must pass 2 out of 3 runs (67%)

## Interaction Fields

Each interaction represents one turn of conversation with the agent.

| Field | Type | Required | Description |
|:------|:-----|:---------|:------------|
| `text` | string | Yes | User message to send |
| `sly_data` | object | No | sly\_data to attach to the message |
| `timeout_in_seconds` | integer | No | Override timeout for this interaction |
| `chat_filter` | string | No | Filter for processing the response |
| `response` | object | No | Expected response validation rules |

### response

The response object specifies how to validate the agent's response.

#### response.text

Validates the text content of the response.

| Field | Type | Description |
|:------|:-----|:------------|
| `value` | string | Exact string match |
| `not_value` | string | Must not equal this string |
| `less` | integer | Response length must be less than this |
| `not_less` | integer | Response length must not be less than this |
| `greater` | integer | Response length must be greater than this |
| `not_greater` | integer | Response length must not be greater than this |
| `keywords` | array | All keywords must appear in the response |
| `not_keywords` | array | None of these keywords should appear |
| `gist` | array | LLM-validated semantic checks (see below) |
| `not_gist` | array | LLM-validated negative semantic checks |

#### response.sly\_data

Validates the sly\_data returned by the agent.

| Field | Type | Description |
|:------|:-----|:------------|
| `value` | object | Exact match of sly\_data dictionary |
| `keywords` | array | Keys that must exist in sly\_data |
| `not_keywords` | array | Keys that must not exist in sly\_data |

#### response.structure

Validates the structure of specific sly\_data keys.

```hocon
"response": {
    "structure": {
        "order_id": {
            "type": "string",
            "not_value": ""
        }
    }
}
```

## Gist Validation

The `gist` field uses an LLM discriminator to validate response semantics rather than
doing brittle string matching. Each entry is a natural language description of what the
response should contain:

```hocon
"response": {
    "text": {
        "gist": [
            "The response contains a greeting directed at Mars.",
            "The greeting is two words or fewer."
        ],
        "not_gist": [
            "The response asks for clarification.",
            "The response refuses to greet Mars."
        ]
    }
}
```

Each gist statement is independently evaluated. All `gist` statements must pass and all
`not_gist` statements must fail for the test to pass.

## Multi-Turn Test

```hocon
{
    "agent": "weather_assistant",
    "interactions": [
        {
            "text": "What's the weather in NYC?",
            "response": {
                "text": {
                    "gist": ["Contains weather information for New York City."]
                }
            }
        },
        {
            "text": "How about tomorrow?",
            "response": {
                "text": {
                    "gist": [
                        "Contains a weather forecast.",
                        "References New York City or NYC from the previous context."
                    ]
                }
            }
        }
    ]
}
```

## Test with sly\_data

```hocon
{
    "agent": "coffee_finder",
    "interactions": [
        {
            "sly_data": {
                "time": "8 am",
                "location": "office"
            },
            "text": "Where can I get coffee?",
            "response": {
                "text": {
                    "gist": [
                        "Suggests getting coffee at or near the office.",
                        "The suggestion is appropriate for early morning."
                    ]
                }
            }
        }
    ]
}
```
