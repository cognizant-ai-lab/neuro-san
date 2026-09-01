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

## Modes

Selected with `--mode`:

| Mode | What it does |
|---|---|
| `record` | Forwards each request to the external LLM host (endpoint + key from env vars), relays the real response back to neuro-san, and tees it into the cassette file (capturing wall-clock latency). |
| `playback` | Serves responses from the cassette by matching the canonical request signature. No network, no tokens. An unmatched request fails hard with HTTP 504. |
| `hybrid` | Like `playback`, but a cache **miss** falls through to the real host (when an upstream is configured via the env vars below), records the result into the **current** cassette, and returns it — a self-healing cassette that fills in gaps on demand. With no upstream configured, a miss behaves like plain playback (504). |

**Only successful responses are recorded.** In `record` and `hybrid` modes a
non-2xx upstream response (rate limit `429`, auth `401`, upstream `5xx`, …) is
relayed back to the caller but **not** written to the cassette, so a transient
failure can't poison it — a later retry records a good response instead. To
repair a cassette recorded before this behavior existed, see
[Cleaning a cassette](#cleaning-a-cassette).

### Cleaning a cassette

`cleanup_cassette.py` repairs a cassette left with failure responses by an
interrupted or throttled recording session, making it safe for playback/hybrid:

- Single-response entries with a non-2xx status are dropped.
- Multi-response entries have their non-2xx variants removed; the entry is
  dropped only if no successful variant remains.
- All other data (requests, keys, latencies, unknown fields, `version`) is
  preserved.

```bash
export PYTHONPATH=$(pwd)
# Non-destructive: writes <cassette>.clean.json next to the input.
python -m tests.record_playback_llm_server.cleanup_cassette session.cassette.json
# Overwrite in place (a <cassette>.bak is made first).
python -m tests.record_playback_llm_server.cleanup_cassette session.cassette.json --in-place
# Report what would be removed without writing anything.
python -m tests.record_playback_llm_server.cleanup_cassette session.cassette.json --dry-run
```

Note: cleanup is status-based; a provider that returns HTTP 200 with an error
body is not detected.

### Multi-response (round-robin)

The `--multi-response` flag is orthogonal to `record`/`playback`:

- In **record**, every *distinct* response seen for a given request is
  accumulated under that request's key (identical repeats are de-duplicated,
  ignoring latency). Because recording forwards each occurrence to the real
  host, this captures the LLM's natural variability — at the cost of one real
  call per occurrence.
- In **playback**, the recorded responses for a key are served **round-robin**.

Without the flag (the default), a request maps to a single response
(last-writer-wins on record, deterministic on playback). Under concurrency the
round-robin order is not guaranteed stable — use the default when strict
determinism matters.

## External host configuration (record and hybrid modes)

The external LLM host is configured **only** via environment variables. It is
required in `record` mode and used for cache-miss fetches in `hybrid` mode:

| Variable | Purpose |
|---|---|
| `RECORD_PLAYBACK_UPSTREAM_BASE_URL` | Base URL of the real host, e.g. `https://api.openai.com` or `https://api.openai.com/v1`. The OpenAI-style `/v1` segment is optional and is appended when absent. Required in record mode; optional in hybrid mode. |
| `RECORD_PLAYBACK_UPSTREAM_API_KEY` | Bearer credential for that host. Optional (a warning is logged if absent, for hosts that need no auth). |
| `RECORD_PLAYBACK_UPSTREAM_REQUEST_TIMEOUT_SECONDS` | Whole-request timeout when forwarding to the real host. Default `600`. |
| `RECORD_PLAYBACK_UPSTREAM_CONNECT_TIMEOUT_SECONDS` | Connection timeout when forwarding to the real host. Default `30`. |
| `RECORD_PLAYBACK_UPSTREAM_MAX_CLIENTS` | Maximum simultaneous in-flight requests to the real host before further requests queue. Default `100`. |

The incoming request's own `openai_api_key` (pointed at this proxy) is ignored
and replaced with the real credential above.

All timeout/limit variables accept a positive number; an invalid or
non-positive value logs a warning and falls back to the default. They apply
whenever the proxy contacts the network (record mode, and hybrid-mode
misses); plain playback never does.

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

# Or self-healing playback: serve from the cassette, but fetch+record any miss.
export RECORD_PLAYBACK_UPSTREAM_BASE_URL="https://api.openai.com/v1"
export RECORD_PLAYBACK_UPSTREAM_API_KEY="sk-..."
python -m tests.record_playback_llm_server.record_playback_llm_server \
    --mode hybrid --cassette ./session.cassette.json

# Capture response variability and replay it round-robin:
python -m tests.record_playback_llm_server.record_playback_llm_server \
    --mode record --multi-response --cassette ./session.cassette.json
python -m tests.record_playback_llm_server.record_playback_llm_server \
    --mode playback --multi-response --cassette ./session.cassette.json
```

### CLI options

| Flag | Default | Description |
|---|---|---|
| `--host` | `localhost` | Bind interface. |
| `--port` | `8899` | Bind port (differs from the mock's 8888 so both can run at once). |
| `--mode` | _(required)_ | `record`, `playback`, or `hybrid` (playback + record-on-miss). |
| `--cassette` | `./llm_cassette.json` | Path to the cassette JSON file. |
| `--multi-response` | off | Record (and hybrid misses) save every distinct response per request; playback serves them round-robin. |
| `--stream-replay-delay` | `0.0` | Seconds between streamed SSE frames during playback, to emulate inter-token cadence. `0` replays as fast as possible. |
| `--delay-mode` | `none` | Up-front per-response delay before serving a cache hit: `none`, `recorded`, `fixed`, `random`. |
| `--delay-seconds` | `0.0` | Delay for `--delay-mode fixed`. |
| `--delay-min` / `--delay-max` | `0.0` / `0.0` | Range for `--delay-mode random` (uniform). |

### Playback delay

`--delay-mode` emulates how long the real LLM took, applied as an up-front
sleep **before serving each cache hit** (playback mode, and hybrid hits). It is
independent of `--stream-replay-delay` (which paces the gaps *between* streamed
SSE frames):

| `--delay-mode` | Delay applied per response |
|---|---|
| `none` (default) | None — serve immediately. |
| `recorded` | The response's own recorded wall-clock latency: `first_byte_seconds` (time-to-first-token) for streams, `latency_seconds` for one-shot responses. |
| `fixed` | A constant `--delay-seconds`. |
| `random` | Uniform in `[--delay-min, --delay-max]`. |

With `--multi-response`, `recorded` honors **each variant's own** recorded
latency: since playback rotates through the responses and each carries its own
`latency_seconds`, each turn is delayed by exactly what that recording took.

```bash
# Replay with each response delayed by exactly what it took to record:
python -m tests.record_playback_llm_server.record_playback_llm_server \
    --mode playback --cassette ./session.cassette.json --delay-mode recorded

# Replay with a random 0.5–2.0s delay per response:
python -m tests.record_playback_llm_server.record_playback_llm_server \
    --mode playback --cassette ./session.cassette.json \
    --delay-mode random --delay-min 0.5 --delay-max 2.0
```

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
        "body": { "id": "chatcmpl-...", "choices": [ ... ] },
        "latency_seconds": 1.732
      }
    }
  ]
}
```

A streamed response is stored with `"kind": "stream"` and a `"chunks"` array
of the individual SSE frames (`data: {...}\n\n`, terminated by
`data: [DONE]\n\n`), re-emitted verbatim on playback. Stream responses also
record `"first_byte_seconds"` (time to the first chunk — the LLM's
time-to-first-token) alongside `"latency_seconds"` (total).

**Latency** (`latency_seconds`, and `first_byte_seconds` for streams) is the
wall-clock time the real host took, captured during recording. `--delay-mode
recorded` reproduces per-response timing on playback (see
[Playback delay](#playback-delay)), using `first_byte_seconds` for streams and
`latency_seconds` for one-shot responses. `--stream-replay-delay` remains an
independent knob for inter-frame pacing.

**Multi-response** entries replace the single `"response"` with a `"responses"`
array holding each distinct variant (each with its own latency); playback
rotates through them. Single-response cassettes (with `"response"`) still
replay unchanged, so existing fixtures keep working.

## Internal layout

One class per file:

| File | Class | Responsibility |
|---|---|---|
| `record_playback_llm_server.py` | `RecordPlaybackLlmServer` | CLI entry point; reads env config, builds the app, runs the loop. |
| `proxy_state.py` | `ProxyState` | Process-wide state: mode, cassette, upstream client, hybrid responder, replay pacing, round-robin cursors. |
| `proxy_handler.py` | `ProxyHandler` | Shared record/playback/hybrid logic for both proxied endpoints (base class). |
| `chat_completions_handler.py` | `ChatCompletionsHandler` | `POST /v1/chat/completions`. |
| `models_handler.py` | `ModelsHandler` | `GET /v1/models`. |
| `health_handler.py` | `HealthHandler` | `GET /healthz`. |
| `upstream_client.py` | `UpstreamClient` | Async HTTP client to the real host (record mode), one-shot and streaming. |
| `cassette.py` | `Cassette` | Load/lookup/store/atomic-save of recorded interactions (single and multi-response). |
| `playback_delay.py` | `PlaybackDelay` | Per-response up-front delay policy (none/recorded/fixed/random). |
| `request_canonicalizer.py` | `RequestCanonicalizer` | Canonical request string + sha256 cassette key. |
| `cleanup_cassette.py` | `CassetteCleaner` | Standalone tool: strip non-2xx (failure) responses from a cassette. |

## Known limitations

- **OpenAI wire format only.** Hosts reachable via an OpenAI-compatible
  `base_url` are supported. Anthropic/Bedrock/Gemini native wire formats are
  not handled.
- **Playback miss = hard 504.** By design, so tests surface gaps
  deterministically rather than silently faking a response. Re-record when the
  agent network or inputs change.
- **Round-robin order isn't concurrency-stable.** With `--multi-response`,
  which recorded variant a given concurrent request receives is not
  guaranteed run-to-run. Use single-response mode when strict determinism
  matters.
- **Single process, single event loop.** A test tool: no supervisor, no
  metrics, no auth. Bind to `localhost`.
