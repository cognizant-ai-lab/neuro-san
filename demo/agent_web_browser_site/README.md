# Agent Web Browser (static site, neuro-san-lite runtime)

A small static web app — HTML + CSS + the compiled `neuro_san_lite.js`
bundle — that loads an Agent Web network in a browser tab and runs the chat
against the origin using your own LLM key (BYOK).

This directory is **served by each neuro-san origin itself** when
`AGENT_LANDING_ENABLE=1` and `AGENT_STATIC_DIR` are set; the demo
`start_origins.sh` does both. So you don't run a separate web server — you
just visit any origin's `/` directly.

## What you see at `http://<origin>/`

```
┌──────────────────────────────────────────────────────────────────────┐
│ Agent Web   localhost:8801                                       [⚙] │
│                            [ <url bar with prefilled selection> ] [Load] │
├──────────────┬──────────────────────────────────────┬─────────────────┤
│ Networks     │ banner: ⚠ key not set / ✓ loaded ... │ Network calls   │
│ on origin    │ ──────────────────────────────────── │ ───────────────│
│              │ [user]   I want to fly to Tokyo...   │ GET  /network  │
│ ▸ flight_    │ [agent]  Here are three options...   │ POST /tool/   │
│   finder     │ ...                                  │ POST /str...  │
│              │                                      │                │
│   ledger     │ [ type a message... ]         [Send] │                │
└──────────────┴──────────────────────────────────────┴────────────────┘
```

The left panel is populated from the JSON bootstrap (`window.AGENT_WEB_BOOTSTRAP`)
that the origin's `LandingHandler` injects into the page. Clicking a network
prefills the URL bar and clears the chat for a fresh session.

## Run locally

```bash
./demo/agent_web/start_origins.sh
open http://localhost:8801/    # or :8802, or :8803
```

That's it. Each origin serves its own landing page plus the chat UI bundle.

In settings (⚙) paste your `ANTHROPIC_API_KEY` once; it lives in this
browser's `localStorage` and is sent to the origin via `sly_data.llm_config`
on each chat turn (BYOK — never persisted on the origin).

You can also paste a URL from a different origin into the URL bar and chat
with that one — same UI, different agent.

## How it works

1. You visit `http://localhost:8801/` (a real Tornado-served URL on the
   flights origin).
2. The origin's `LandingHandler` builds the page by:
   - Listing the published networks it publishes (from its
     `AgentNetworkStorage`),
   - Reading `${AGENT_STATIC_DIR}/index.html` (this file's `index.html`),
   - Injecting `<script>window.AGENT_WEB_BOOTSTRAP = {...}</script>` into
     `<head>`,
   - Returning the result as `text/html`.
3. Your browser loads `app.js` and `neuro_san_lite.js` from the same origin
   via `StaticFileHandler`.
4. `app.js` reads `window.AGENT_WEB_BOOTSTRAP` and renders the networks
   panel. Clicking a network prefills the URL bar and resets the chat.
5. On each chat turn, `runAgentTurn()` from the bundle:
   - `fetch()`es the notebook URL,
   - extracts and verifies the wire config,
   - threads the user's LLM key into `sly_data.llm_config`,
   - POSTs to streaming_chat,
   - yields `agent`, `thinking`, `network`, `done` events.
6. The UI renders those events into bubbles and trace entries.

## Deploying

This directory deploys as plain static. The `LandingHandler` is built into
neuro-san itself — any neuro-san origin can serve a landing page by setting
`AGENT_LANDING_ENABLE=1` (and optionally `AGENT_STATIC_DIR=/path/to/site/`
to also serve a chat UI bundle from `/`).

For a hosted public deploy:

```bash
python build_scripts/build_neuro_san_lite.py
# `dist/neuro_san_lite.js` and a copy in demo/agent_web_browser_site/.
# Deploy each origin as a normal neuro-san server with:
#   AGENT_LANDING_ENABLE=1
#   AGENT_STATIC_DIR=/path/to/demo/agent_web_browser_site
```

## Security model

- Keys live in `localStorage` on the user's machine.
- LLM calls happen at the origin servers using the key the runtime threaded
  into `sly_data.llm_config`. The origin uses it for that request only and
  never persists it (see neuro-san's `replace_any_required_api_keys`).
- The static site has no server of its own — it's served by each origin's
  Tornado HTTP server alongside the protocol endpoints. Same-origin policy
  applies as expected.
- Cross-origin URL bar pastes work because origins set
  `Access-Control-Allow-Origin: *` on `/network` and `/streaming_chat`
  responses (via `AGENT_ALLOW_CORS_HEADERS=1`).

## Files

| File | Purpose |
|---|---|
| `index.html` | Page shell. Loaded by the origin's `LandingHandler`. |
| `style.css` | Styling. |
| `app.js` | UI logic; imports `runAgentTurn` from the bundle. |
| `neuro_san_lite.js` | Built TypeScript runtime bundle. Generated. |
| `smoke.mjs` | Node-based smoke test against a live origin. |
| `README.md` | This file. |
