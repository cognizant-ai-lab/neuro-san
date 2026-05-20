# neuro-san-client

The browser-portable subset of the neuro-san runtime, sufficient to **load and
run an Agent Web network from a browser tab**. Pairs 1-to-1 with
`neuro-san-lite-js` (the TypeScript port).

## Scope

This package contains ONLY the code paths a runtime ("browser") needs:

* Wire-config extraction and verification (protocol-version check,
  same-origin check, integrity hash check on shipped client-side tool source).
* `sly_data` redaction (`allow.to_downstream` / `allow.from_downstream` /
  `allow.to_upstream` filters).
* The agent network's in-memory model.
* A chat-loop driver that streams against an origin's `/streaming_chat`
  endpoint with BYOK (bring-your-own-key) `sly_data.llm_config`.

It does NOT contain anything server-side: no HOCON parsing (the wire form is
JSON), no `tornado`, no `grpcio`, no `aiohttp`, no `langchain`, no provider
SDKs. The LLM lives at the *origin*; the client only needs to talk HTTP and
manage state.

## Forcing function

Every module in `src/neuro_san_client/` is restricted to an allowlist of
imports enforced by `build_scripts/build_neuro_san_lite.py`. Adding a non-
portable import fails the build with a precise error pointing at the offending
line. See that script for the allowlist.

## Pairing with the TypeScript port

Every Python module in this package must have a corresponding TS file in
`neuro-san-lite-js/src/`. The build script checks both directions.
