# Agent Web demo — cross-publisher trip planner

Three independent neuro-san "origins" composing a single trip-planning chat.
Each origin is its own publisher (its own brand, its own backend, its own
billing). A user visits one of them in their browser, the runtime fetches the
agent network, and the chat unfolds across all three with cross-origin calls.

It is the working demonstration of the
[Agent Web design doc](../../docs/agent_web_design.md).

## The story

| Publisher | Port | Brand | Published network | Server-side tools | Client-side tools |
|---|---|---|---|---|---|
| `flights.example` | 8801 | ✈ SkyHop Airways | `flight_finder` | `search_flights`, `book_hold` | — |
| `hotels.example` | 8802 | 🏨 Nest Hotels | `hotel_finder` | `search_hotels` | `score_hotel` |
| `travelgenius.example` | 8803 | ✨ TravelGenius | `trip_planner` | — | `total_cost` |

`trip_planner` references the other two by URL. A user opens it in their
browser tab, types one trip request, and the agent composes flights + hotels
+ scoring + summing + booking across all three origins. Every LLM call along
the chain is billed to the user's own API key (BYOK).

---

## Deployment guide — step by step

Assumes a fresh clone of `neuro-san` and the `claude/determined-engelbart-e28048`
branch checked out. Tested on macOS and Linux with Python 3.11+ and Node 18+.

### Step 1 — Python environment (one-time)

```bash
cd /path/to/neuro-san
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

`pip install -e .` installs neuro-san itself plus its base deps. Provider
packages (`langchain-anthropic`) are auto-installed by `start_origins.sh`
the first time it runs.

### Step 2 — Node + JS dependencies (one-time)

The browser UI is a TypeScript bundle that has to be compiled. If you don't
have Node:

```bash
# macOS
brew install node

# anywhere with nvm
nvm install --lts
```

Then build the bundle:

```bash
python build_scripts/build_neuro_san_lite.py
```

What this does, in order:
1. Lints the Python in `neuro-san-client/` against the import allowlist.
2. Cross-checks that every Python module has a matching TypeScript port.
3. On first run, runs `npm install` inside `neuro-san-lite-js/` (~10–20 s).
4. Runs the TS unit tests (89 of them).
5. Runs `tsc --noEmit` for typechecking.
6. Bundles `src/index.ts` → `dist/neuro_san_lite.js` (single ES module).
7. Mirrors the bundle into `demo/agent_web_browser_site/` so each origin can
   serve it as a static asset.

Successful output ends with:

```
[build] OK — dist/neuro_san_lite.js is up to date
```

Re-run this command after every `git pull` if you want the latest bundle.

### Step 3 — Start the three origins

```bash
./demo/agent_web/start_origins.sh
```

Three neuro-san processes come up:

| URL | What it serves |
|---|---|
| http://localhost:8801 | flights.example — SkyHop Airways branding |
| http://localhost:8802 | hotels.example — Nest Hotels branding |
| http://localhost:8803 | travelgenius.example — TravelGenius branding |

Each origin serves both the Agent Web protocol endpoints (`/api/v1/*`) AND
the static browser UI (HTML + the `neuro_san_lite.js` bundle), so you don't
need a separate dev server. The script auto-installs `langchain-anthropic`
into your venv if you don't have it yet.

Logs go to `/tmp/agent_web_demo_<origin>.log`. PIDs to
`/tmp/agent_web_demo_<origin>.pid`. Refusal-to-start on a double-launch is
the safe default.

### Step 4 — Open the demo

```bash
open http://localhost:8803/        # macOS
xdg-open http://localhost:8803/    # Linux
# …or paste the URL into Chrome/Firefox
```

You'll see TravelGenius's purple landing page:

- **Top:** brand name and logo.
- **Left:** the agent network visualization (`trip_planner` at top,
  `flight_finder` + `hotel_finder` + `total_cost` as children). Nodes light
  up live as the chat runs.
- **Center:** the chat (prefilled with the network's sample query).
- **Right:** the network-calls trace panel — includes both the browser's
  direct fetches AND the cross-origin calls travelgenius makes server-side
  on your behalf (marked `via localhost:8803`).

### Step 5 — Set your LLM API key (one-time per origin per browser)

Click the ⚙ button in the top-right. Paste your `ANTHROPIC_API_KEY` (from
console.anthropic.com) into the "Anthropic key" field. Click **Save**.

The key lives in your browser's `localStorage` under that origin's storage
scope. It is never sent to the origin operator — only forwarded with each
request to the LLM provider via `sly_data.llm_config` (BYOK). The origin
uses it for that request only and never persists it.

You only strictly need to set the key on `:8803` (TravelGenius) for the
trip-planner demo, because `trip_planner` forwards the key down the chain
to flight_finder and hotel_finder via `allow.to_downstream.sly_data`. If
you also want to chat directly with `:8801` or `:8802`, set keys there too.

### Step 6 — Send the message

The chat input is prefilled with:

```
SFO to Tokyo around June 14-21, hotel near Shinjuku under $300/night with a gym. My email is bob@example.com.
```

Click **Send**. Watch:

- `trip_planner` in the left panel pulse blue (it's actively running).
- A few seconds later, `flight_finder` lights up — its cross-origin call is
  in flight. The right panel records a `via localhost:8803` entry.
- Then `hotel_finder` lights up the same way.
- Both children get a ✓ checkmark badge when their calls return 200.
- `trip_planner` returns to "done" once the full reply is composed.
- The chat shows real flight IDs (`UA-0837`, `JL-0001`, etc.) and hotel
  names (`Hotel Gracery Shinjuku`, `Shinjuku Granbell`) — proof the
  cross-origin calls actually reached the private inventories.

### Step 7 — Visit the other two origins (optional)

```bash
open http://localhost:8801/    # SkyHop Airways
open http://localhost:8802/    # Nest Hotels
```

Same protocol, same bundle, completely different visual brand. Each one
shows that origin's own network (`flight_finder` and `hotel_finder`
respectively) with its own graph. This is the demonstration that different
businesses can ship the same protocol with their own look and feel.

### Step 8 — Stop everything

```bash
./demo/agent_web/stop_origins.sh
```

---

## Optional paths

### Headless verification (no LLM key, no browser)

Walks the entire Agent Web protocol with 65 deterministic checks. Useful
to confirm a fresh setup before touching the UI:

```bash
.venv/bin/python ./demo/agent_web/verify_demo.py
```

Expected: `65/65 checks passed.`

### Headless chat from the Python CLI

If you'd rather drive the chat from a script:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
.venv/bin/python -m neuro_san.client.agent_web_browser \
  --url http://localhost:8803/api/v1/trip_planner/network \
  --message 'SFO to Tokyo around 2026-06-14 for 7 nights, hotel near Shinjuku under $300/night with a gym.' \
  --sly-data passenger_email=bob@example.com \
  --no-interactive
```

This is the same protocol the browser bundle exercises, run from Python.
The CLI auto-injects your env's API key into `sly_data.llm_config` so you
don't have to type it.

### Using OpenAI instead of Anthropic

The demo HOCONs default to `claude-haiku`. To switch:

```bash
sed -i.bak 's/"claude-haiku"/"gpt-4o-mini"/' \
  demo/agent_web/{flights,hotels,travelgenius}/registries/*.hocon
rm demo/agent_web/*/registries/*.bak
./demo/agent_web/stop_origins.sh && ./demo/agent_web/start_origins.sh
```

Then paste your `OPENAI_API_KEY` into the ⚙ "OpenAI key" field in the
browser.

### Public deployment

For a real internet-facing demo, point your DNS at three reachable hosts,
update the HOCONs' cross-origin URLs to those hostnames, terminate TLS
appropriately, and tighten the CORS policy. The HOCONs, build, and bundle
work identically across `localhost` and public hosts — only the URLs need
to change. See the *Networking requirements* section in
[`docs/agent_web_design.md`](../../docs/agent_web_design.md) for the
details (DNS, TLS, CORS, inter-origin auth).

---

## Billing model — full-chain BYOK

The chain bills whoever started the chain. Concretely:

- All three HOCONs declare `"anthropic_api_key": "sly_data"`.
  `replace_any_required_api_keys` (in neuro-san core) resolves the sentinel
  from each request's `sly_data.llm_config.anthropic_api_key` and uses it
  for that request only.
- `trip_planner.hocon`'s `allow.to_downstream.sly_data` includes
  `llm_config: true`, so the user's key crosses the cross-origin boundary
  into flight_finder and hotel_finder.
- Each sub-origin then uses the **same** key for its own LLM calls.

Bob's key drives every LLM call when Bob is chatting. Alice's key drives
every LLM call when Alice is chatting. The same `flight_finder` code answers
both. Origin operators never subsidize anyone's tokens.

**Trust implication:** every origin in the chain sees the calling client's
key. Only invoke chains you trust — same as how using a website implies
trusting all the sub-services it embeds.

---

## What `verify_demo.py` proves

`./demo/agent_web/verify_demo.py` walks the full Agent Web protocol and
asserts every piece works end-to-end. 65 checks spanning:

1. Each origin's `GET /api/v1/{network}/network` returns a well-formed
   Jupyter notebook with protocol-version-stamped metadata.
2. The scrubbed wire form has **no `class:`**, **no `toolbox:`**, **no
   server secrets** anywhere. Server-side tools carry `coded_tool_url`;
   client-side tools carry `client_side_source` plus a SHA-256 integrity hash.
3. `POST /api/v1/{network}/tool/{tool_name}` works for server-side coded
   tools; the same endpoint refuses to invoke `client_side`-marked tools.
4. `sly_data` redaction at the `/tool/` boundary obeys `allow.to_downstream`
   (limiting what reaches the tool) and `allow.from_downstream` (limiting
   what reaches the caller).
5. Browser-side `verify_wire_config` enforces protocol-version match,
   same-origin on `coded_tool_url`, and (at activation time) SHA-256
   integrity on shipped source. Tampered source is rejected; cross-origin
   coded-tool URLs are rejected.
6. `ClientSideToolActivation` actually executes the shipped Python in the
   runtime process.
7. The wire shape that `RemoteToolActivation` sends round-trips through the
   origin's `/tool/` endpoint and returns the expected payload.
8. A full deterministic scenario walks the exact tool sequence an LLM-driven
   `trip_planner` front-man would walk, ending in a booking code.

---

## Demonstrated WWW-of-agents properties

| Property | Where shown |
|---|---|
| Multiple independent origins composed without coordination | `trip_planner` references flights + hotels by URL with no shared deployment |
| Client orchestrates with client's own credentials (full-chain BYOK) | Every LLM call in the chain uses the key the browser threaded into `sly_data` |
| Server-side data stays private | Flight + hotel inventories live behind `/tool/`; tool source is never sent |
| Client-side tools execute locally | `score_hotel`, `total_cost` ship as Python with integrity hashes |
| Cross-origin agent linking (the `<a href>` analogue) | `tools: ["http://localhost:8801/flight_finder", ...]` |
| Per-field cross-origin private-data flow control | `passenger_email` crosses; `browser_secret` is stripped |
| Integrity-checked shipped code (the SRI analogue) | SHA-256 hash on `client_side_source`, runtime refuses on mismatch |
| Same-origin policy on tool fetches | Runtime refuses `coded_tool_url`s pointing away from the notebook origin |
| Per-origin branding | Each origin's HOCON declares `metadata.branding`; LandingHandler injects CSS variables |
| Live cross-origin trace surfaced to the browser | `ExternalActivation` emits structured `network_call` events; the runner renders them in the trace panel marked `via :8803` |

---

## File layout

```
demo/agent_web/
├── flights/
│   ├── registries/
│   │   ├── manifest.hocon              # publish: true
│   │   └── flight_finder.hocon         # branding: SkyHop Airways
│   └── coded_tools/flight_finder/
│       ├── search_flights.py           # private inventory
│       └── book_hold.py                # uses passenger_email sly_data
├── hotels/
│   ├── registries/
│   │   ├── manifest.hocon
│   │   └── hotel_finder.hocon          # branding: Nest Hotels
│   └── coded_tools/hotel_finder/
│       ├── search_hotels.py
│       └── score_hotel.py              # client_side: true; ships to runtime
├── travelgenius/
│   ├── registries/
│   │   ├── manifest.hocon
│   │   └── trip_planner.hocon          # branding: TravelGenius
│   └── coded_tools/trip_planner/
│       └── total_cost.py               # client_side: true
├── start_origins.sh  /  stop_origins.sh
├── verify_demo.py                      # 65-check headless verifier
└── README.md                           # this file
```

Related directories elsewhere in the repo:

```
demo/agent_web_browser_site/    # static UI bundle (HTML + CSS + JS) served by each origin
neuro-san-client/               # the Python carve-out (browser-portable runtime subset)
neuro-san-lite-js/              # the TypeScript port (compiled to neuro_san_lite.js)
build_scripts/build_neuro_san_lite.py   # lint + tests + build pipeline
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `sh: vitest: command not found` during build | `npm install` not yet run in `neuro-san-lite-js/` on a fresh clone | Re-run `python build_scripts/build_neuro_san_lite.py` — the script now auto-installs node_modules on the first pass. |
| Build fails with `langchain_anthropic` import error at runtime | Provider package missing | `pip install langchain-anthropic` (or `./start_origins.sh` will do it automatically) |
| Browser banner says "⚠ no LLM key configured" | localStorage on this origin has no key yet | Open ⚙ on this origin's tab, paste your key, click Save. |
| Chat hangs > 30 s with no agent reply | LLM provider auth failure or rate limit | Watch `/tmp/agent_web_demo_travelgenius.log` for the actual error |
| `flight_finder`/`hotel_finder` nodes don't light up | Cross-origin calls failed; check sub-origin logs | `tail /tmp/agent_web_demo_flights.log /tmp/agent_web_demo_hotels.log` |
| `./demo/agent_web/start_origins.sh` says "already running" | Stale pid file | `./demo/agent_web/stop_origins.sh && ./demo/agent_web/start_origins.sh` |
| Origins start but `:port/readyz` never returns | Port in use by another process | `lsof -i :8801` and kill the conflicting process |
