# Record / Playback LLM Server

A standalone OpenAI-compatible HTTP proxy for **recording** a neuro-san
session against a real external LLM host and **playing it back** offline.

Two goals:

1. **Free** — record once against the paid host, then replay from disk with
   zero token cost.
2. **Repeatable** — replaying byte-identical recorded responses removes the
   random nature of LLM output, so load and regression tests become
   deterministic.

It is wire-compatible with the OpenAI Chat Completions API, so any neuro-san
agent network configured for `class = "openai"` can be redirected at it with a
single `openai_api_base` change — the same seam the sibling `mock_llm_server`
uses.

There is **no synthetic mode** here: every response is either forwarded from
the real host (record) or served from a prior recording (playback).

## Modes

| Mode | What it does |
|---|---|
| `record` | Forwards each request to the external LLM host (endpoint + key from env vars), relays the real response back to neuro-san, and tees it into the cassette file. |
| `playback` | Serves responses from the cassette by matching the canonical request signature. No network, no tokens. An unmatched request fails hard with HTTP 504. |

## External host configuration (record mode)

The external LLM host is configured **only** via environment variables:

| Variable | Purpose |
|---|---|
| `RECORD_PLAYBACK_UPSTREAM_BASE_URL` | Base URL of the real host, including the version segment. e.g. `https://api.openai.com/v1`. Required in record mode. |
| `RECORD_PLAYBACK_UPSTREAM_API_KEY` | Bearer credential for that host. Optional (a warning is logged if absent, for hosts that need no auth). |
| `RECORD_PLAYBACK_UPSTREAM_REQUEST_TIMEOUT_SECONDS` | Whole-request timeout when forwarding to the real host. Default `600`. |
| `RECORD_PLAYBACK_UPSTREAM_CONNECT_TIMEOUT_SECONDS` | Connection timeout when forwarding to the real host. Default `30`. |
| `RECORD_PLAYBACK_UPSTREAM_MAX_CLIENTS` | Maximum simultaneous in-flight requests to the real host before further requests queue. Default `100`. |

The incoming request's own `openai_api_key` (pointed at this proxy) is ignored
and replaced with the real credential above.

All timeout/limit variables accept a positive number; an invalid or
non-positive value logs a warning and falls back to the default. They apply in
**record mode only** (playback never contacts the network).

> **If you are seeing timeout errors while recording under load**, raising
> `RECORD_PLAYBACK_UPSTREAM_REQUEST_TIMEOUT_SECONDS` alone may not be enough:
> Tornado's client serves only `max_clients` requests at once and queues the
> rest, and time spent queued counts against the request timeout. Raise
> `RECORD_PLAYBACK_UPSTREAM_MAX_CLIENTS` to at least your peak concurrency.

## Running

The package is runnable as a module:

```bash
export PYTHONPATH=$(pwd)

# 1) Record a session against the real host (costs tokens, once).
export RECORD_PLAYBACK_UPSTREAM_BASE_URL="https://api.openai.com/v1"
export RECORD_PLAYBACK_UPSTREAM_API_KEY="sk-..."
python -m tests.record_playback_llm_server.record_playback_llm_server \
    --mode record --port 8899 --cassette ./session.cassette.json

# ... run your load/integration test against neuro-san, then Ctrl-C ...

# 2) Replay it forever, for free, deterministically (no env vars needed).
python -m tests.record_playback_llm_server.record_playback_llm_server \
    --mode playback --port 8899 --cassette ./session.cassette.json
```

### CLI options

| Flag | Default | Description |
|---|---|---|
| `--host` | `localhost` | Bind interface. |
| `--port` | `8899` | Bind port (differs from the mock's 8888 so both can run at once). |
| `--mode` | _(required)_ | `record` or `playback`. |
| `--cassette` | `./llm_cassette.json` | Path to the cassette JSON file. |
| `--stream-replay-delay` | `0.0` | Seconds between streamed SSE frames during playback, to emulate inter-token cadence. `0` replays as fast as possible. |

## Pointing a neuro-san agent network at the proxy

```hocon
llm_config {
    class = "openai"
    model_name = "gpt-4.1"
    openai_api_base = "http://localhost:8899/v1"
    openai_api_key = "not-needed"
}
```

- `openai_api_base` must include the `/v1` path segment.
- Use the **same** agent network and inputs for record and playback — the
  match key is derived from the request, so a changed prompt is a new
  (unrecorded) request.

## How matching works

The response of an LLM is non-deterministic, but the **request** is a
deterministic function of the agent network plus its inputs. In a multi-turn
agent flow, each request embeds the previous responses (assistant messages,
`tool_call` ids, tool results). Because playback returns **byte-identical**
recorded responses, every downstream request reconstructs identically — so a
hash of the canonicalized request body is a stable key across the whole
conversation.

Canonicalization (`RequestCanonicalizer`):

- Parses the JSON body and re-serializes it with **sorted keys**, so
  incidental key ordering does not change the key.
- Keeps the `stream` flag as part of the key (a streamed request and a
  one-shot request map to different recorded responses).
- Drops any fields listed in `VOLATILE_BODY_KEYS` (empty by default; extend it
  if a client is found to inject a per-run random value into the body).

The key is `sha256(f"{METHOD} {path}\n{canonical_body}")`.

## Cassette format

An ordered, human-diffable JSON array — commit it to git as a test fixture:

```json
{
  "version": 1,
  "entries": [
    {
      "key": "<sha256>",
      "method": "POST",
      "path": "/chat/completions",
      "request": "POST /chat/completions\n{...canonical body...}",
      "response": {
        "kind": "json",
        "status": 200,
        "body": { "id": "chatcmpl-...", "choices": [ ... ] }
      }
    }
  ]
}
```

A streamed response is stored with `"kind": "stream"` and a `"chunks"` array
of the individual SSE frames (`data: {...}\n\n`, terminated by
`data: [DONE]\n\n`), re-emitted verbatim on playback.

## Internal layout

One class per file:

| File | Class | Responsibility |
|---|---|---|
| `record_playback_llm_server.py` | `RecordPlaybackLlmServer` | CLI entry point; reads env config, builds the app, runs the loop. |
| `proxy_state.py` | `ProxyState` | Process-wide state: mode, cassette, upstream client, replay pacing. |
| `proxy_handler.py` | `ProxyHandler` | Shared record/playback logic for both proxied endpoints (base class). |
| `chat_completions_handler.py` | `ChatCompletionsHandler` | `POST /v1/chat/completions`. |
| `models_handler.py` | `ModelsHandler` | `GET /v1/models`. |
| `health_handler.py` | `HealthHandler` | `GET /healthz`. |
| `upstream_client.py` | `UpstreamClient` | Async HTTP client to the real host (record mode), one-shot and streaming. |
| `cassette.py` | `Cassette` | Load/lookup/store/atomic-save of recorded interactions. |
| `request_canonicalizer.py` | `RequestCanonicalizer` | Canonical request string + sha256 cassette key. |

## Known limitations

- **OpenAI wire format only.** Hosts reachable via an OpenAI-compatible
  `base_url` are supported. Anthropic/Bedrock/Gemini native wire formats are
  not handled.
- **Playback miss = hard 504.** By design, so tests surface gaps
  deterministically rather than silently faking a response. Re-record when the
  agent network or inputs change.
- **One key → one response.** Identical requests replay the same recorded
  response. Recorded response variety for the same request is not preserved.
- **Single process, single event loop.** A test tool: no supervisor, no
  metrics, no auth. Bind to `localhost`.
