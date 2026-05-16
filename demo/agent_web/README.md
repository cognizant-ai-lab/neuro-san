# Agent Web demo — cross-publisher trip planner

This demo brings up three independent neuro-san "origins" and walks a trip
planning scenario that exercises every piece of the Agent Web MVP. It is the
companion to [docs/agent_web_design.md](../../docs/agent_web_design.md).

## The story

Three "publishers", with no business relationship to each other, each publish
a distributable agent network:

| Publisher | Port | Distributable network | Server-side tools | Client-side tools |
|---|---|---|---|---|
| `flights.example` | 8801 | `flight_finder` | `search_flights`, `book_hold` | — |
| `hotels.example` | 8802 | `hotel_finder` | `search_hotels` | `score_hotel` |
| `travelgenius.example` | 8803 | `trip_planner` | — | `total_cost` |

`trip_planner` references the other two via cross-origin agent URLs. A user
("Bob") opens `trip_planner` in a browser/runtime, and Bob's runtime
composes flights + hotels + scoring + summing + booking — using **Bob's
LLM API key** for the top-level orchestration and the **origins' server-private
data** for inventory and bookings.

## Running it

### Prerequisites

The demo HOCONs default to `claude-haiku`, so you'll need:

```bash
pip install -e .                       # neuro-san itself (one time)
pip install 'langchain-anthropic>=1.0' # provider package the HOCONs reference
export ANTHROPIC_API_KEY=sk-ant-...
```

`start_origins.sh` will auto-install `langchain-anthropic` if it can't import
it, so you can usually skip the second step.

If you'd rather use OpenAI (which neuro-san already pulls in by default),
swap the model name in all three HOCONs first:

```bash
sed -i.bak 's/"claude-haiku"/"gpt-4o-mini"/' \
  demo/agent_web/{flights,hotels,travelgenius}/registries/*.hocon
rm demo/agent_web/*/registries/*.bak
export OPENAI_API_KEY=sk-...
```

### Run

```bash
# from the repo root
./demo/agent_web/start_origins.sh

# then either run the headless verification (no LLM needed):
/tmp/agent_web_venv/bin/python ./demo/agent_web/verify_demo.py

# ...or chat with the trip planner (requires ANTHROPIC_API_KEY in env):
/tmp/agent_web_venv/bin/python -m neuro_san.client.agent_web_browser \
  --url http://localhost:8803/api/v1/trip_planner/network \
  --message 'SFO to Tokyo around 2026-06-14 for 7 nights, hotel near Shinjuku under $300/night with a gym. My email is bob@example.com.' \
  --sly-data passenger_email=bob@example.com \
  --no-interactive

./demo/agent_web/stop_origins.sh
```

## What `verify_demo.py` proves

The verification script walks the full Agent Web protocol and asserts every
piece works end-to-end. **65 checks** spanning:

1. Each origin's `GET /api/v1/{network}/network` returns a well-formed
   Jupyter notebook with protocol-version-stamped metadata.
2. The scrubbed wire form has **no `class:`**, **no `toolbox:`**, **no
   server secrets** anywhere. Server-side tools carry `coded_tool_url`;
   client-side tools carry `client_side_source` plus a SHA-256 integrity hash.
3. `POST /api/v1/{network}/tool/{tool_name}` works for server-side coded
   tools; the same endpoint correctly refuses to invoke `client_side`-marked
   tools.
4. `sly_data` redaction at the `/tool/` boundary obeys
   `allow.to_downstream` (limiting what reaches the tool) and
   `allow.from_downstream` (limiting what reaches the caller).
5. Browser-side `verify_wire_config` enforces protocol-version match,
   same-origin on `coded_tool_url`, and (at activation time) SHA-256
   integrity on shipped source. Tampered source is rejected; cross-origin
   coded-tool URLs are rejected.
6. `ClientSideToolActivation` actually executes the shipped Python in the
   runtime process (Pyodide wasm in production browser deployments).
7. The wire shape that `RemoteToolActivation` sends round-trips through the
   origin's `/tool/` endpoint and returns the expected payload.
8. A full deterministic scenario walks the exact tool sequence an LLM-driven
   `trip_planner` front-man would walk, ending in a booking code. This
   exercises the cross-origin compose: `search_flights` (origin A) →
   `search_hotels` (origin B) → `score_hotel` (shipped from B, run in
   client) → `total_cost` (shipped from C, run in client) → `book_hold`
   (origin A) with `passenger_email` crossing the sly_data CORS boundary.

The only thing `verify_demo.py` does not exercise is the LLM-driven loop
that decides the dispatch order; that's the standard neuro-san chat-session
machinery the rest of the codebase tests. When the chat CLI is run with a
real API key, the same protocol primitives are dispatched in whatever order
the LLM picks.

## Demonstrated WWW-of-agents properties

| Property | Where shown |
|---|---|
| Multiple independent origins composed without coordination | trip_planner references flights + hotels by URL with no shared deployment |
| Client orchestrates with client's own credentials | The runtime makes LLM calls; the origins never see Bob's key |
| Server-side data stays private | Flight + hotel inventories live behind `/tool/`; tool source is never sent |
| Client-side tools execute locally | `score_hotel`, `total_cost` ship as Python and run in the runtime |
| Cross-origin agent linking (the `<a href>` analogue) | `tools: ["http://localhost:8801/flight_finder", ...]` |
| Per-field cross-origin private-data flow control | `passenger_email` crosses; `browser_secret` is stripped |
| Integrity-checked shipped code (the SRI analogue) | SHA-256 hash on `client_side_source`, runtime refuses on mismatch |
| Same-origin policy on tool fetches | Runtime refuses `coded_tool_url`s pointing away from the notebook origin |
| User-driven composition / remixing | Edit `trip_planner.hocon`'s tool URLs, swap an origin, re-run |

## File layout

```
demo/agent_web/
├── flights/
│   ├── registries/
│   │   ├── manifest.hocon        # distributable: true
│   │   └── flight_finder.hocon
│   └── coded_tools/flight_finder/
│       ├── search_flights.py     # server-side, has private inventory
│       └── book_hold.py          # server-side, uses passenger_email sly_data
├── hotels/
│   ├── registries/
│   │   ├── manifest.hocon
│   │   └── hotel_finder.hocon
│   └── coded_tools/hotel_finder/
│       ├── search_hotels.py      # server-side
│       └── score_hotel.py        # client_side: true; ships to runtime
├── travelgenius/
│   ├── registries/
│   │   ├── manifest.hocon
│   │   └── trip_planner.hocon    # references the two above by URL
│   └── coded_tools/trip_planner/
│       └── total_cost.py         # client_side: true
├── start_origins.sh / stop_origins.sh
├── verify_demo.py
└── README.md (this file)
```
