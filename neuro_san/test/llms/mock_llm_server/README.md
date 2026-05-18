# Mock LLM Server

A standalone HTTP service that mimics the OpenAI Chat Completions API. It is
intended for **load testing, integration testing, and local development** of
neuro-san agent networks without incurring real LLM token costs, hitting rate
limits, or depending on network connectivity to a hosted provider.

The mock is wire-compatible with the OpenAI client SDK, so any neuro-san agent
network configured for `class = "openai"` can be redirected at it with a single
`openai_api_base` change.

## What it provides

| Endpoint | Method | Purpose |
|---|---|---|
| `/v1/chat/completions` | POST | OpenAI-compatible chat completions. Honors `stream: true` via Server-Sent Events. |
| `/v1/models` | GET | Lists the single configured mock model. |
| `/healthz` | GET | Liveness probe; returns `{"status": "ok"}`. |

Behavioral guarantees:

- Returns either a **tool call** or a **text completion**, deterministic with
  respect to the request shape:
  - If the request includes `tools` *and* the message history does **not**
    already contain a `role: "tool"` entry, the mock returns a randomly chosen
    tool call with minimally valid arguments derived from the tool's JSON
    Schema parameters.
  - Otherwise, it returns canned text from a rotating list.
- Adds **random latency** sampled uniformly from `[min_latency, max_latency]`
  before responding, to emulate real LLM thinking time.
- In streaming mode, additionally inserts `stream_token_delay` seconds between
  word chunks to emulate inter-token latency.

## Running the server

The package is runnable as a module:

```bash
python -m neuro_san.test.llms.mock_llm_server.mock_llm_server [OPTIONS]
```

From a checked-out neuro-san repo, that becomes:

```bash
export PYTHONPATH=$(pwd)
python -m neuro_san.test.llms.mock_llm_server.mock_llm_server --port 8888
```

It logs a one-line startup banner and then blocks until interrupted with
`Ctrl-C`.

### CLI options

| Flag | Default | Description |
|---|---|---|
| `--host` | `0.0.0.0` | Bind interface. Use `127.0.0.1` to restrict to loopback. |
| `--port` | `8888` | Bind port. |
| `--model-name` | `mock-model` | Model id reported by `/v1/models` and echoed in completion responses. |
| `--min-latency` | `0.1` | Lower bound (seconds) for the simulated thinking delay. |
| `--max-latency` | `1.5` | Upper bound (seconds) for the simulated thinking delay. |
| `--stream-token-delay` | `0.02` | Delay between streamed word chunks, text path only. Tool-call streams ignore this. |
| `--responses-file` | _(none)_ | Path to a JSON file containing an array of strings. If supplied, replaces the built-in canned responses. |

### Custom canned responses

Provide a JSON file containing an array of strings:

```json
[
  "First canned response.",
  "Second canned response.",
  "Third canned response."
]
```

Then start with `--responses-file path/to/file.json`. The server rotates
through the list, repeating from the start once exhausted.

## Pointing a neuro-san agent network at the mock

In any agent's `llm_config`, override the OpenAI base URL:

```hocon
llm_config {
    class = "openai"
    model_name = "mock-model"
    openai_api_base = "http://localhost:8888/v1"
    openai_api_key = "not-needed"
}
```

Notes:

- `openai_api_base` must include the `/v1` path segment — the OpenAI client SDK
  is strict about this.
- The `openai_api_key` value is required by the client SDK but is not validated
  by the mock. Any non-empty string works.
- If the neuro-san service runs in a container and the mock runs on the host,
  use a routable hostname (e.g. `host.docker.internal` on Docker Desktop)
  rather than `localhost`.

## Smoke-testing the running server

A quick health check:

```bash
curl -s http://localhost:8888/healthz
# -> {"status": "ok"}
```

A non-streaming text completion:

```bash
curl -s -X POST http://localhost:8888/v1/chat/completions \
    -H 'content-type: application/json' \
    -d '{
        "model": "mock-model",
        "messages": [{"role": "user", "content": "hello"}]
    }' | python -m json.tool
```

A non-streaming tool call:

```bash
curl -s -X POST http://localhost:8888/v1/chat/completions \
    -H 'content-type: application/json' \
    -d '{
        "model": "mock-model",
        "messages": [{"role": "user", "content": "hello"}],
        "tools": [{
            "type": "function",
            "function": {
                "name": "hello_tool",
                "parameters": {
                    "type": "object",
                    "properties": {"who": {"type": "string"}},
                    "required": ["who"]
                }
            }
        }]
    }' | python -m json.tool
```

A streaming completion:

```bash
curl -sN -X POST http://localhost:8888/v1/chat/completions \
    -H 'content-type: application/json' \
    -d '{
        "model": "mock-model",
        "stream": true,
        "messages": [{"role": "user", "content": "hello"}]
    }'
```

Each line in the streaming response is `data: {json}\n\n`, terminated by
`data: [DONE]\n\n`, exactly as the OpenAI streaming protocol specifies.

## How the mock decides what to return

The decision is purely a function of the incoming request shape. Token content
is **not** inspected. The logic is:

```
request has "tools"
        ↓
        AND
        ↓
message history does NOT contain any {"role": "tool", ...}
        ↓
   TRUE → return a tool_call to a randomly chosen tool
   FALSE → return next canned text response
```

This is enough to drive an agent network through its full call graph: each
agent's first turn sees no tool-result yet, so the mock issues a tool call.
The sub-agent that handles the call then makes its own model invocation,
which similarly issues a sub-tool call, and so on. When a leaf-level
`CodedTool` returns, the agent's next turn sees a `role: "tool"` message and
the mock issues a text completion, terminating the loop.

### Argument fabrication

When emitting a tool call, the mock builds arguments that minimally satisfy
the tool's `parameters` JSON Schema:

| Schema `type` | Generated value |
|---|---|
| `string` | first `enum` value if present, else `"test"` |
| `integer` | `0` |
| `number` | `0.0` |
| `boolean` | `true` |
| `array` | `[]` |
| `object` | recursively populates each `required` property |

Only `required` properties are populated. Optional parameters are omitted. If
your `CodedTool` reads optional args, the mock will not exercise that path —
add them to `required` in the schema if you want them filled in.

## Typical use cases

**Load testing the agent execution engine**: point your normal benchmark
client (Locust, `wrk`, your own driver) at the neuro-san service while the
agent's `llm_config` points at the mock. Real network sockets, real
serialization, real LangChain runnable pipeline; no LLM cost, no rate limit.

**Reproducing latency-sensitive behaviour**: tune `--min-latency` /
`--max-latency` to match your production LLM's p50 / p99 to reproduce
streaming back-pressure, request-timeout edge cases, and concurrent-request
saturation under realistic timing.

**Integration tests in CI**: start the mock as a background process at the
start of a test job and have the neuro-san service talk to it. Avoids any
external network dependency. Use `--min-latency 0 --max-latency 0
--stream-token-delay 0` for the fastest possible turnaround.

**Validating client streaming**: confirm that downstream clients correctly
consume both SSE-streamed and one-shot JSON responses, including responses
that contain tool calls. The mock emits the exact OpenAI wire format.

## Known limitations

- **Token counts in responses are always zero**. The mock fills `usage` with
  `prompt_tokens: 0, completion_tokens: 0, total_tokens: 0`. Anything that
  depends on real usage data won't work.
- **No image or vision support**. Multimodal request payloads are accepted
  syntactically but treated as text-only.
- **No function-strict / structured-output mode**. The `response_format` field
  in the request body is ignored.
- **Tool choice is random**. The mock picks one tool uniformly at random
  rather than honoring a `tool_choice` field. Branch coverage is statistical,
  not exhaustive.
- **Single process, single event loop**. Designed for testing, not production.
  No process supervisor, no graceful drain, no metrics endpoint.
- **No authentication**. Anyone with network access to the port can use it.
  Bind to `127.0.0.1` for development.

## Internal layout

The package follows the one-class-per-file convention. For developers
extending the mock:

| File | Class | Responsibility |
|---|---|---|
| `mock_llm_server.py` | `MockLlmServer` | CLI entry point. Builds the Tornado application, parses args, runs the asyncio loop. |
| `mock_state.py` | `MockState` | Shared process-wide state: configuration, response cycler, latency sleep helper. Also owns `DEFAULT_RESPONSES` and the `load_responses` JSON file reader. |
| `chat_completions_handler.py` | `ChatCompletionsHandler` | Implements `POST /v1/chat/completions`. Contains the streaming and non-streaming code paths. |
| `models_handler.py` | `ModelsHandler` | Implements `GET /v1/models`. |
| `health_handler.py` | `HealthHandler` | Implements `GET /healthz`. |
| `tool_arg_generator.py` | `ToolArgGenerator` | Generates minimal-valid argument values for a tool's JSON Schema parameters. |

To add a new endpoint, create a new handler class in its own file and
register the route in `MockLlmServer.build_app`.

To change the response cadence (e.g. emit a different number of SSE chunks
per token), edit `ChatCompletionsHandler._stream_text_response` or
`ChatCompletionsHandler._stream_tool_call`.
