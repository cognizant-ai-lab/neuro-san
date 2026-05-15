# Agent Web: A WWW of Agents — Design Document

Status: Draft for review. No code has been written against this design yet.

## 1. Vision

We want a "world wide web of agents" with the same shape as the world wide web:

- Anyone can publish an agent network at a URL.
- Anyone can "browse to" that URL with a runtime ("browser") of their choice.
- The runtime fetches the agent network and executes it locally, using the client's own LLM credentials.
- The agent can call back to its origin server for capabilities the client cannot provide (private data, server-only code, paid APIs).
- The agent can reference and call other agents at other origins, with the same security trade-offs the web has always made.

The neuro-san project already has most of the machinery to make this work. This document describes the smallest set of additions that turns a neuro-san server into an "agent web server," and uses Jupyter — specifically the notebook format as the wire artifact and JupyterLite as the first reference runtime — to provide the "browser" side.

## 2. The analogy

| Web | Agent Web |
|---|---|
| HTML document | An agent network spec |
| `.html` file as a published artifact | A `.ipynb` notebook with the agent spec in a raw JSON cell |
| Web server | A neuro-san server with `distributable: true` agent networks |
| Browser | A neuro-san client runtime; first reference is a JupyterLite extension |
| JavaScript executed in the browser sandbox | Python coded tools shipped as source, executed in Pyodide's wasm sandbox |
| Server endpoints / XHR / `fetch()` | `POST /api/v1/{agent}/tool/{tool_name}` against the origin |
| `<a href>` to another site | `tools: ["/http://other-origin/some_agent"]` — already exists via `ExternalActivation` |
| `<iframe>` to a third-party widget | MCP tool reference — already supported |
| Same-origin policy | Same-origin enforcement on tool-fetch endpoints |
| CORS | `sly_data` `allow.to_downstream` / `from_downstream` / `to_upstream` filters; HTTP CORS headers for browser-direct requests |
| Subresource Integrity (SRI) | Integrity hash on shipped client-side tool source |
| "View source" | Open the notebook; inspect the spec cell |

## 3. Why Jupyter (notebook + JupyterLite)

We chose this stack instead of a custom Chrome extension after evaluating four options: a custom Python sandbox, a TypeScript reimplementation in a browser extension, bare Pyodide in a custom extension, and Jupyter-based.

The Jupyter path collapses the most work onto things we do not have to build:

| What we would have built | What Jupyter provides |
|---|---|
| Wire-format specification | `.ipynb` is already standardized |
| Static viewer / "view source" | GitHub, nbviewer |
| Browser UI shell | JupyterLab |
| Sandboxed in-browser Python | JupyterLite (Pyodide / wasm) |
| Streaming kernel ↔ UI | Jupyter `comms` / `ipywidgets` |
| Discovery and linking | GitHub search, nbviewer URLs, mybinder |
| Distribution channel | PyPI extension, JupyterLite static hosting |
| Extension lifecycle | JupyterLab extension system |

We also explicitly accept what Jupyter does **not** give us:

- A mainstream non-developer UX. The first audience for this is people who already know what HOCON and LangChain are. A non-Jupyter Chrome extension consuming the same notebook format remains a viable follow-up project.
- A uniform sandbox across runtimes. JupyterLite is wasm-sandboxed; desktop Jupyter, VS Code's notebook viewer, and Colab are not. The protocol is the same in all of them, but the trust tier differs. We will be explicit about this (see §9).

## 4. Architecture overview

```
                +----------------------------------+
                |  Origin server (neuro-san)       |
                |                                  |
                |  GET  /api/v1/{name}/network     |  <-- serves notebook
                |  POST /api/v1/{name}/tool/{tn}   |  <-- server-side tool RPC
                |  POST /api/v1/{name}/streaming   |  <-- existing chat (unchanged)
                |                                  |
                |  manifest.hocon: distributable   |
                |  HOCON scrubber                  |
                +----------------------------------+
                            ^         ^
                            |         |
                  fetch     |         | fetch /tool
                  notebook  |         |
                            |         |
                +-----------+---------+------------+
                |  Runtime / "browser"             |
                |                                  |
                |  JupyterLite (reference)         |
                |   - Pyodide kernel               |
                |   - neuro_san_client package     |
                |   - chat widget                  |
                |   - local LLM key storage        |
                |                                  |
                |  Other valid runtimes:           |
                |   - Desktop Jupyter / VS Code    |
                |   - Future Chrome extension      |
                |   - Headless CLI ("curl")        |
                +----------------------------------+
                            |
                            v
                +----------------------------------+
                |  LLM providers (OpenAI, etc.)    |
                |  - direct from runtime           |
                |  - client's own API key          |
                +----------------------------------+
```

Two boundaries matter:

- **Runtime ↔ origin**: HTTP. Fetches the notebook, invokes server-side tools, sends/receives `sly_data` redacted at the boundary.
- **Runtime ↔ LLM provider**: HTTP. Direct, using the client's own credentials. Origin never sees them.

Cross-origin agent calls go through the existing `ExternalActivation` flow — runtime → other-origin streaming-chat — and recursively follow the same model.

## 5. Server-side additions (in-tree in neuro-san)

All additions are additive. Existing behavior (`serve`, `public`, `mcp`) is unchanged.

### 5.1 New manifest flag: `distributable`

The manifest entry for an agent network can now declare `distributable: true`. When set, the server exposes the network over the two new endpoints below.

```hocon
{
  "math_guy.hocon": {
    "serve": true,
    "public": true,
    "distributable": true
  }
}
```

`distributable` is independent of `serve`. A network can be both server-executed (existing model) and distributable (new model) at the same time.

`ManifestNetworkValidator` is extended to accept the new key. `AgentNetworkStorage` exposes a `is_distributable(name)` predicate.

### 5.2 HOCON scrubber

A new component, `DistributableNetworkScrubber`, transforms an `AgentNetwork`'s config dict into a **wire form** safe to publish. Logic:

1. **Strip server secrets** from `llm_config` and from any nested `llm_config` overrides:
   - Drop keys whose name matches a configurable secret pattern (default: `api_key`, `api_secret`, `aws_*`, `azure_*_key`, `*_token`).
   - This includes any value substituted from `commondefs.replacement_strings`.
2. **Resolve `commondefs`** so the client does not need to. Substitution is performed in-place; the wire form has no `commondefs` block.
3. **Rewrite each agent's coded-tool reference** according to mode:
   - If the agent's spec has `client_side: true`: include the tool's Python source inline as a base64-encoded string in a new `client_side_source` field, plus a SHA-256 `integrity` hash. The `class` key is removed.
   - Otherwise (default, server-side): replace `class` (or `toolbox`) with `coded_tool_url: "https://{origin}/api/v1/{network}/tool/{agent_name}"`. The class name is dropped entirely; the client cannot see what Python class would have run.
4. **Validate** that the resulting wire form contains no `class`, no `toolbox`, no `commondefs`, and no recognizable secret values. If any remain, refuse to serve and log a structured error so the operator can fix the network.
5. **Stamp protocol metadata**: `agent_web.protocol_version`, `agent_web.origin`, `agent_web.network_name`, `agent_web.published_at`.

The scrubber is pure-function: `(AgentNetwork, origin) → wire_config: dict`. It has unit tests independent of the HTTP layer.

### 5.3 Endpoint: `GET /api/v1/{name}/network`

Returns a Jupyter notebook (`application/x-ipynb+json`) containing the scrubbed wire form. The notebook has exactly four cells in MVP:

1. **Markdown cell** — human-facing title, description from network metadata, sample queries, link back to the origin.
2. **Raw JSON cell** — `application/x-agent-network+json` mimetype, body is the scrubbed wire config produced by §5.2. This is the machine-readable spec.
3. **Code cell** (kickoff) — exactly:
   ```python
   from neuro_san_client import open_agent_from_notebook
   open_agent_from_notebook()
   ```
   On execution, this reads the raw cell from the current notebook context, instantiates the agent, and starts a chat widget.
4. **Markdown cell** — short "what runs where" footer: which tools are client-side, which are server-side, version stamp.

The handler is gated by `is_distributable(name)`. It honors the existing `agent_policy` authorizer (operators can require auth to read the notebook). CORS headers are set so that JupyterLite (running from a different origin) can `fetch()` the notebook.

### 5.4 Endpoint: `POST /api/v1/{name}/tool/{tool_name}`

Invokes a single server-side coded tool. Request body:

```json
{
  "args": { ... },
  "sly_data": { ... }
}
```

Behavior:

1. Look up `name` in `AgentNetworkStorage`; reject if `distributable` is false or the agent name does not exist.
2. Find the agent named `tool_name` inside that network; reject if not found, or if it has `client_side: true` (those are not callable via this endpoint).
3. Reject if the agent has no `class` / `toolbox` reference (this endpoint is only for coded tools, not LLM agents).
4. Apply the network's `allow.to_downstream.sly_data` rule (treat the caller as the "downstream" direction): incoming `sly_data` is filtered through `SlyDataRedactor` before the tool sees it.
5. Resolve and invoke the tool via the existing `AbstractClassActivation.attempt_invoke` machinery in an `InvocationContext` configured with no journal output to the caller (the tool's internal logs go to the server's logger, not back to the client).
6. Apply `allow.from_downstream.sly_data` to any `sly_data` the tool returned.
7. Respond:
   ```json
   {
     "tool_output": "...",
     "sly_data": { ... },
     "tool_error": false
   }
   ```

The endpoint is **the single point of trust** between the runtime and the origin server. Server secrets (API keys to paid services, database credentials, etc.) only live behind it. The tool's Python source is never sent over the wire.

CORS: tightly configured. Default policy is to accept any origin (the network is distributable, after all), but the operator can narrow it via server config. Preflight `OPTIONS` is handled.

### 5.5 New activation: `RemoteToolActivation`

Sibling of `ClassActivation`, `ToolboxActivation`, `ExternalActivation`. Selected by `AgentToolFactory` when an agent spec has a `coded_tool_url` field (which the scrubber injects).

Behavior on invoke:

1. Apply `allow.to_downstream.sly_data` redaction to the outgoing `sly_data`.
2. `POST` to `coded_tool_url` with `{args, sly_data}`.
3. On 200, parse `{tool_output, sly_data}` from the response.
4. Apply `allow.from_downstream.sly_data` redaction to the returned `sly_data`.
5. Return an `AIMessage` with `tool_output` as content; merge the redacted `sly_data` into the active `InvocationContext`'s sly_data.
6. On network or HTTP error, return an error message in the same shape `ExternalActivation` does today, so the LLM loop can recover gracefully.

`RemoteToolActivation` is shared between the server and the client runtime — it is part of the neuro-san package, not the client-only package. A server-resident agent network can use a `coded_tool_url` to call another origin's tool, just as the runtime does.

### 5.6 Carve-out: `neuro_san_client` subpackage

Today `neuro_san` mixes server, client, and runtime concerns. For Pyodide we need a subset that:

- Has no `tornado`, no `grpcio`, no manifest watcher, no `tornado_main_loop`, no protobuf-generated server stubs.
- Contains: `AgentNetwork`, `AgentNetworkStorage`, `DataDrivenChatSession`, `AgentToolRegistry`, all `activations/*` types, `run_context/*`, `message_processing/*`, `journals/*`, `interfaces/*`, `internals/graph/*`, `coded_tool` base interface, sly_data redactor, `RemoteToolActivation`, and the new "open agent from notebook" helper described in §6.3.
- Imports cleanly under Pyodide's import graph (we will run the import set against Pyodide's package compatibility list and shim or replace anything missing).

This carve-out is the design contract for "what can run in a browser." It will be referenced by the JupyterLite extension and any future runtime (custom Chrome extension, mobile, etc.).

The carve-out is internal restructuring; from outside, `import neuro_san_client` is the public API for runtimes.

## 6. The notebook wire format

### 6.1 Notebook structure

A served notebook has the following cells, in order:

1. Markdown — title, description, sample queries.
2. Raw — mimetype `application/x-agent-network+json`, body is the scrubbed wire config (see §6.2).
3. Code — kickoff cell, fixed content (see §5.3).
4. Markdown — version stamp and tool/origin disclosure.

Notebook-level `metadata` contains:

```json
{
  "agent_web": {
    "protocol_version": "0.1",
    "origin": "https://alice.example",
    "network_name": "math_guy",
    "published_at": "2026-05-13T14:22:01Z",
    "kernelspec_hint": "python3"
  }
}
```

The `kernelspec` of the notebook is set to a vanilla Python 3 kernel so the notebook opens in any standard Jupyter environment, including JupyterLite.

### 6.2 Wire config (raw cell body)

```json
{
  "$schema": "https://agentweb.dev/schemas/v0.1/network.json",
  "protocol_version": "0.1",
  "origin": "https://alice.example",
  "network_name": "math_guy",
  "llm_config": {
    "model_name": "gpt-4o-mini",
    "required_llm_config": ["api_key"]
  },
  "middleware": [ ... ],
  "tools": [
    {
      "name": "front_man",
      "function": { "description": "...", "parameters": { ... } },
      "instructions": "...",
      "tools": ["client_calc", "server_ledger"]
    },
    {
      "name": "client_calc",
      "function": { "description": "Performs arithmetic", "parameters": { ... } },
      "client_side": true,
      "client_side_source": "<base64 of calculator.py>",
      "integrity": "sha256-..."
    },
    {
      "name": "server_ledger",
      "function": { "description": "Looks up a value in the alice.example ledger",
                    "parameters": { ... } },
      "coded_tool_url": "https://alice.example/api/v1/math_guy/tool/server_ledger",
      "allow": { "to_downstream": { ... }, "from_downstream": { ... } }
    }
  ]
}
```

Notes:

- `class` and `toolbox` are absent. Their presence is a scrubber bug.
- `commondefs` is absent. All substitution is pre-resolved.
- Any `api_key` or recognized-secret field in `llm_config` is absent. Clients are expected to supply credentials.
- `required_llm_config` lists which provider-credential fields the runtime must inject from local credential storage.

### 6.3 Runtime helper: `open_agent_from_notebook()`

Defined in `neuro_san_client`. Steps:

1. Locate the current notebook's raw cell with mimetype `application/x-agent-network+json` (via the Jupyter `comms` API or, in JupyterLite, via the `ipynb` JSON in scope).
2. Parse it.
3. Verify `protocol_version` is one the client supports; refuse on mismatch.
4. For each `tools[].client_side_source`: verify the SHA-256 integrity hash matches the source bytes. Refuse on mismatch.
5. For each `tools[].coded_tool_url`: verify it is same-origin with notebook-level `origin` metadata. Refuse on mismatch.
6. Build an in-memory `AgentNetwork(config, network_name)` and register it into a fresh, single-network `AgentNetworkStorage`.
7. Read the user's LLM credentials from local storage (browser `localStorage` in JupyterLite, environment variables in desktop runtimes). Inject them into the network's effective `llm_config` for this session only (in-memory; never persisted back into the notebook).
8. Spawn a `DirectAgentSession`-equivalent against the storage and bind it to a chat widget (`ipywidgets`-based for MVP).
9. Stream messages from the chat session to the widget; stream user input from the widget back to the session.

The helper is the entire "kickoff" surface from the user's perspective: run that cell, get a chat box.

## 7. Coded tools — both modes

Authoring guidance (will become §X of the agent HOCON reference doc):

### 7.1 Server-side coded tools (default)

Same as today. Implement `CodedTool`, declare `class: "..."` in the agent spec. The class lives on the server, runs on the server, and the runtime invokes it via `coded_tool_url`. Server has full access to its env vars, filesystem, and network. Source is never shipped.

This is the right choice when the tool:
- Uses paid APIs and the author wants to bill the call.
- Reads private databases.
- Holds proprietary logic.
- Needs server resources the client cannot have.

### 7.2 Client-side coded tools (`client_side: true`)

Implement `CodedTool` exactly as today. Add `client_side: true` to the agent spec. The scrubber will:

- Read the tool's source file from `AGENT_TOOL_PATH` resolution.
- Base64-encode it.
- Stamp a SHA-256 hash.
- Embed both in the wire config.

The tool runs **inside the runtime's wasm sandbox** (JupyterLite case) or **inside the local trusted Python process** (desktop Jupyter case). It has only:

- The `args` the LLM passed it.
- The `sly_data` the runtime threaded through (subject to `allow.*` redaction).
- Whatever Pyodide / the local interpreter exposes — no server env vars, no `coded_tool_url`s, no origin's filesystem.

This is the right choice when the tool:
- Does pure computation (math, formatting, string manipulation, local file parsing in Pyodide's VFS).
- Should run with zero per-call latency.
- Should work offline once the notebook is loaded.
- Does not need server secrets.

A tool can be authored once and toggled between modes by changing the manifest flag. The same Python class works in both.

### 7.3 Mixed networks

A single agent network can mix freely. The MVP demo (§10) does exactly this.

## 8. `sly_data` semantics across the runtime ↔ origin boundary

`sly_data` is neuro-san's existing private context channel. It is already redacted on cross-server boundaries by `SlyDataRedactor` using the `allow.to_downstream` / `from_downstream` / `to_upstream` rules in each agent's spec. We reuse this verbatim:

- **Runtime → origin (tool call)**: `RemoteToolActivation` applies `allow.to_downstream.sly_data` to the outgoing `sly_data`. The origin's `/tool/` endpoint applies the *same* filter on receipt as a defense-in-depth check (the network's author wrote the rule; both ends honor it).
- **Origin → runtime (tool return)**: the `/tool/` endpoint applies `allow.from_downstream.sly_data` before responding. `RemoteToolActivation` applies it again on receipt.
- **Final response to the human user**: `allow.to_upstream.sly_data` is applied at the front-man boundary, exactly as today.

No new redaction rules are introduced. We are reusing the model that already exists for cross-server agent calls.

LLM credentials supplied by the user via `sly_data.llm_config` (the existing mechanism) work unchanged in the runtime context.

## 9. Security model

### 9.1 Trust tiers by runtime

We are explicit that not all runtimes are equally sandboxed.

| Runtime | Sandbox | Trust tier |
|---|---|---|
| JupyterLite (Pyodide / wasm in a browser tab) | Strong (wasm + browser same-origin) | "Browse the agent web safely" |
| Future custom Chrome extension on Pyodide | Strong (wasm + extension boundary) | Same as above |
| Desktop Jupyter, VS Code notebooks, Colab | None — kernel runs as the user | "Run a trusted local app" |
| Headless `curl`-style CLI | None | "Make API calls only" |

This is the same distinction the web makes between "browse a URL" (safe) and "download and run a binary" (caveat emptor). The protocol is the same in all cases. The notebook footer (§6.1, cell 4) discloses what runs where so the user knows what they are accepting.

### 9.2 Defenses

- **No server code on the wire.** Server-side tools are only invocable through `/tool/`. The Python class name is not even in the wire config.
- **Same-origin tool fetches.** The runtime refuses to invoke a `coded_tool_url` whose origin does not match notebook-level `agent_web.origin`. Prevents a malicious cross-served notebook from luring a runtime into calling an attacker's endpoint.
- **Integrity hashes on client-side source.** SRI-style. Tampering with the served notebook in transit fails the check; the runtime refuses to load.
- **CORS preflight on `/tool/`.** Operators can restrict which web origins (which "browsers") may call their tools. Default in MVP: allow any origin; document the knob.
- **`sly_data` redaction at every boundary.** Authors declare what crosses; both sides enforce.
- **Server never sees client LLM keys.** Direct runtime → provider; no proxy through origin.
- **No filesystem in Pyodide except its in-memory VFS.** Pyodide cannot escape the wasm boundary. The host page (JupyterLite) decides what slices of `localStorage` to expose.
- **Authorizer hook on `/network` and `/tool/`.** Operators can still require auth to read distributable networks or to call their tools — the existing `agent_policy` chain applies to the new endpoints.

### 9.3 Known limitations (accepted for MVP)

- We do **not** sign notebooks. TLS is the integrity story for transit; SRI is the integrity story for client-side tool source. Origin authentication is the TLS certificate.
- We do **not** rate-limit `/tool/` per caller in MVP. Operators must put a reverse proxy in front if they care.
- We do **not** offer a discovery/search service in MVP. GitHub and nbviewer are the de facto discovery for now.
- We do **not** verify that a client-side tool's Python source is safe to run. It runs in the sandbox; the sandbox is the protection. We do not statically analyze it.

## 10. MVP scope

### 10.1 Demo target

One agent network: `math_guy_web.hocon` (a variant of the existing `math_guy.hocon`). Three agents:

- `front_man` — LLM agent that takes a math word problem and delegates.
- `calculator` — `client_side: true` Python coded tool, ships its source.
- `ledger` — server-side coded tool that pretends to look up a value in a private alice.example ledger.

Manifest declares `math_guy_web.hocon` as `distributable: true`.

The user story:

1. Alice runs `neuro-san serve` with the manifest. Endpoint `https://alice.example/api/v1/math_guy_web/network` returns the notebook.
2. Bob, on a different machine, opens JupyterLite in a browser tab. Bob has the `neuro_san_browser` JupyterLite extension installed.
3. Bob enters `https://alice.example/api/v1/math_guy_web/network` in the extension's URL bar. The extension `fetch()`s the notebook, opens it, and Bob sees the markdown title, the kickoff cell, and the footer.
4. Bob has his `OPENAI_API_KEY` stored in the extension's settings (`localStorage`).
5. Bob runs the kickoff cell. The extension verifies integrity, builds the network in-memory, and renders a chat widget below the cell.
6. Bob types: "What is 17% of 248, plus the alice.example ledger entry for 'rent'?"
7. The runtime's `front_man` agent runs in Pyodide. It calls `calculator` — runs inside the same Pyodide kernel, no round-trip. It calls `ledger` — `RemoteToolActivation` POSTs to `https://alice.example/api/v1/math_guy_web/tool/ledger` with the args. Alice's server executes the Python `Ledger` tool against her private dataset, returns the value. Bob's runtime combines the two and answers.
8. Throughout, every LLM call goes directly from Bob's browser to OpenAI using Bob's API key. Alice never sees it.

This single demo exercises: distributable manifest flag, scrubber, both new endpoints, `RemoteToolActivation`, client-side tool execution under Pyodide, same-origin enforcement, integrity hash check, `sly_data` redaction, LLM-key injection from local storage, and end-to-end streaming.

### 10.2 What is in scope

- `distributable` manifest flag.
- `DistributableNetworkScrubber`.
- `GET /api/v1/{name}/network` returning notebook.
- `POST /api/v1/{name}/tool/{tool_name}`.
- `RemoteToolActivation`.
- `neuro_san_client` carve-out.
- `open_agent_from_notebook()` helper.
- JupyterLite extension: URL bar, key storage, chat widget, integrity verification.
- The `math_guy_web` demo network end-to-end.
- Documentation: this file, plus updates to the manifest and agent HOCON reference docs.

### 10.3 What is out of scope for MVP

- Custom Chrome extension (post-MVP; same protocol).
- HOCON parsing in the runtime (wire format is JSON; HOCON is server-side only).
- Streaming intermediate `sly_data` updates on `/tool/` (one request, one response in MVP — same shape as today's coded tools).
- Cross-origin `/tool/` calls *initiated by client-side coded tools*. Client-side tools in MVP cannot themselves call origin tools; they are leaf computations. (They can still receive `sly_data`.)
- Notebook caching, ETag, conditional GET. Plain `fetch()` every time.
- Multi-version protocol negotiation. `protocol_version` must match exactly between scrubber and runtime in MVP; mismatch refuses to load.
- Authoring tools / a developer kit for building distributable networks. The existing HOCON authoring loop is sufficient; we just add the flag.
- Per-user rate limits or billing on `/tool/`.
- A search/discovery service for distributable networks.
- TypeScript runtime; we deliberately avoid this by using Pyodide.
- Human-readable wire format. JSON in a raw cell is sufficient per agreement.
- MCP-as-server-side-tool from a distributable network. (MCP-as-tool reachable directly from the runtime works automatically because the runtime calls MCP servers over HTTP just like the existing code does.)

## 11. Implementation plan

Sequenced so that each step is independently testable.

### Step 1 — Carve out `neuro_san_client`

Move the runtime-relevant modules into a new subpackage with no server or gRPC dependencies. No behavior change. CI: existing tests pass, plus a new test that imports `neuro_san_client` in a Pyodide-emulated environment (we can use `pyodide-build` or a CI matrix entry on `pyodide/pyodide` Docker image). This step is invasive but creates the contract everything else depends on.

### Step 2 — Manifest flag and scrubber

Add `distributable` to `ManifestNetworkValidator`. Implement `DistributableNetworkScrubber` with full unit tests covering: secret stripping, `commondefs` resolution, `class` → `coded_tool_url` rewrite, `client_side: true` source embedding with hash, refusal-on-leftover-class assertion, refusal-on-leftover-secret assertion.

### Step 3 — `RemoteToolActivation`

Add the new activation type with its own unit tests (mock HTTP, verify `sly_data` redaction in/out, error propagation). Register it in `AgentToolFactory` selection logic (look for `coded_tool_url` before falling back to `class` / `toolbox`).

### Step 4 — Server endpoints

`GET /api/v1/{name}/network` and `POST /api/v1/{name}/tool/{tool_name}`. Integration tests using the existing test scaffolding (HTTP client → handler → real `AgentNetworkStorage`). CORS preflight tests. Authorizer integration tests.

### Step 5 — `open_agent_from_notebook()` helper

Implement in `neuro_san_client`. Unit-tested by feeding it a notebook JSON dict and a fake LLM client, verifying it constructs an `AgentNetwork` with the right agents and that `RemoteToolActivation` is selected for non-client-side tools.

### Step 6 — JupyterLite extension (`neuro_san_browser`)

In a new repo. Minimum surface:

- URL-bar widget that takes an origin + agent name (or a full URL).
- `fetch()` of the notebook, integrity check, load into the notebook UI.
- A "settings" panel for LLM API keys, stored in `localStorage`.
- Pyodide kernel pre-loaded with `neuro_san_client` and Pyodide-compatible LangChain bits.
- A minimal `ipywidgets`-based chat widget that the kickoff cell renders.

This is the bulk of the user-visible work; once steps 1–5 are done, it is mostly assembly.

### Step 7 — Demo network and end-to-end test

`math_guy_web.hocon`, `Calculator` (client-side), `Ledger` (server-side). A scripted end-to-end test that spins up a neuro-san server, runs the JupyterLite extension under a headless browser (Playwright), and verifies the chat completes with the expected answer.

### Step 8 — Documentation

Update `manifest_hocon_reference.md` with the new flag. Update `agent_hocon_reference.md` with `client_side: true`, `coded_tool_url`, and the `allow.*` semantics in this new context. Add a `clients.md` section for the JupyterLite extension. This file (`agent_web_design.md`) stays as the architectural reference.

## 12. Repository structure

We will land the in-tree changes (steps 1–5, 7, 8) in this repository. The JupyterLite extension (step 6) lives in a new sibling repository, depending on `neuro_san_client` from PyPI. This split:

- Keeps the security-critical wasm-runtime work in a dedicated, smaller codebase.
- Lets the extension iterate independently of neuro-san's release cadence.
- Leaves a clean seam for additional runtime implementations (custom Chrome extension, mobile app) that depend on `neuro_san_client` the same way.

## 13. Open questions to resolve during implementation

1. **`coded_tool_url` shape under cross-origin agent calls.** When a distributable network at origin A is loaded into a runtime, and that network references `/http://origin-b/some_agent` via `ExternalActivation`, do server-side tools on origin B get called by the runtime or by origin A? In MVP: by the runtime (preserves "client API keys, client identity"). Tests need to confirm this works as expected through redaction layers.
2. **Pyodide compatibility of the full neuro-san dependency tree.** Specifically `aiohttp`. We expect to either swap to `httpx` with the Pyodide transport or use Pyodide's `aiohttp` port; this is decided during step 1 (the carve-out is the right time to fix it).
3. **Notebook discovery within JupyterLite when there is no "current notebook" context.** `open_agent_from_notebook()` needs a portable way to find its raw cell. We will likely have the JupyterLite extension pass the parsed JSON into the kernel via a `comm` rather than re-parsing the on-disk file. To resolve in step 5.
4. **What to do with networks that have both `serve: true` and `distributable: true` plus secret-bearing `llm_config`.** The scrubber strips secrets for the wire form, but the same network executed server-side still needs them. Confirm the scrubber does not mutate the in-memory `AgentNetwork` used for server-side execution; it should always produce a fresh dict.
5. **Default CORS policy for `/tool/`.** MVP default: `Access-Control-Allow-Origin: *`. We will document the knob for operators to restrict. Decision review point before step 4 lands.

## 14. Naming

Working names used in this document:

- **Agent Web** — the protocol / vision name.
- **`distributable`** — manifest flag.
- **`coded_tool_url`** — wire-config field on a rewritten server-side tool.
- **`client_side`** — wire-config flag for client-shipped tools.
- **`neuro_san_client`** — carved-out subpackage.
- **`neuro_san_browser`** — JupyterLite extension repo.

All are open to bike-shedding in a final review pass before any user-visible API ships.
