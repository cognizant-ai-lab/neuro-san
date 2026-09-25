# Load Test Framework

Fire concurrent requests at a neuro-san server, monitor resource usage,
and report results. Fires real LLM calls via direct HTTP streaming.

Each request runs in a worker thread that opens an `HttpServiceAgentSession`
directly (~1-2 MB per concurrent request). An earlier transport spawned one
`agent_cli` subprocess per request instead, costing ~96 MB each, which made
memory the limit on concurrency; that transport has been removed.

## Contents

- [Quick Start](#quick-start)
- [Test Levels](#test-levels---level)
- [Traffic Modes](#traffic-modes)
- [Flags](#flags)
- [Environment Variables](#environment-variables)
- [Pre-Run Summary and Dry-Run Probe](#pre-run-summary-and-dry-run-probe)
- [Agent Profiles](#agent-profiles)
- [Output](#output)
- [Latency Analysis](#latency-analysis)
- [Exit Codes](#exit-codes)
- [Code Quality](#code-quality)
- [Architecture](#architecture)
- [Cross-Run Comparison](#cross-run-comparison)
- [Trend History](#trend-history)
- [Notes](#notes)

## Quick Start

Start the server (from neuro-san-studio; `ns run --server-only` is the
same thing):

```bash
python -m neuro_san_studio run --server-only 2>&1 | tee logs/server.log
```

Run the load test (from neuro-san):

```bash
export PYTHONPATH=$(pwd)

# Smoke test — does the server respond? (--client-only runs the
# lightweight min profile against an already-running server)
python -m tests.load_tests.load_test_cli --agent hello_world --client-only --no-dry-run

# Standard — with server log (auto-detect from server process)
python -m tests.load_tests.load_test_cli --agent hello_world --level norm \
    --server-log --no-dry-run

# Standard — with server log (explicit path)
python -m tests.load_tests.load_test_cli --agent hello_world --level norm \
    --server-log /path/to/logs/server.log --no-dry-run

# Standard — without server log (resources + tokens)
python -m tests.load_tests.load_test_cli --agent hello_world --level norm --no-dry-run

# Full analysis — with server log
python -m tests.load_tests.load_test_cli --agent hello_world --level adv \
    --ramp --stages 2,4,8 \
    --server-log /path/to/logs/server.log --no-dry-run

# Full analysis — without server log (JSON + tokens, no retries)
python -m tests.load_tests.load_test_cli --agent hello_world --level adv \
    --ramp --stages 2,4,8 --no-dry-run
```

## Test Levels (`--level`)

| Feature                              | min | norm | adv |
|--------------------------------------|-----|------|-----|
| Fire requests + validate responses   |  Y  |  Y   |  Y  |
| Server log (retries, disconnections) |     | auto | auto |
| Resource monitoring (RSS, threads)   |  Y  |  Y   |  Y  |
| Token accounting (from chat stream)  |  Y  |  Y   |  Y  |
| Pool reuse analysis                  |     |      | opt |
| JSON export (`raw_results.json`)     |  Y  |  Y   |  Y  |

> **`min` is not selectable for an all-in-one run.** It is the profile
> used automatically by `--client-only` and `--server-only` (which force
> `min` and enable resource monitoring). Passing `--level min` without
> `--client-only`/`--server-only` is rejected — use `norm` or `adv` for a
> colocated run.

`opt` = available with optional flags; `auto` = on by default when the
target server is local. `--server-log` enables retry counting,
server-side validation, disconnection detection, and pool reuse
analysis. Retry counting covers both neuro-san's own `max_attempts`
retries (`retrying from <ErrorType>`) and retries the LLM provider SDK
performs internally (`Retrying request to ... in ... seconds`, reported
as `Provider SDK retries`); both feed the amplification factor.
At `norm`/`adv` (all-in-one) a server log is expected: it is
auto-detected for a local server (no flag needed when colocated). If a
local log isn't found, the run **prompts** you to continue without it
(or abort); a **remote** host aborts with a pointer to
`--client-only`. Use `--no-server-log` to skip the prompt
and run without log analysis, or `--server-log <path>` for an explicit
file (`--server-log` alone forces auto-detect and aborts if it fails).
It stays off by default at `min`.
Resource monitoring is on automatically at `norm`/`adv` and in the
`min` profile used by `--client-only`/`--server-only`. Token
accounting is enabled at all levels by default (disable with
`--no-tokens`).

**Where LLM/token numbers come from.** Client-side counts arrive in the
chat stream as a token-accounting message, so they require the default
(no `--minimal`); `--minimal` filters that message out server-side and
the `LLM & TOKEN USAGE` section is then omitted for want of data.
Server-side counts are parsed from the server log instead, so they are
unaffected by the filter. A `--client-only` run against a remote host
has no server log to fall back on: with `--minimal` it reports no
tokens at all.

**`adv` level defaults:** 50 requests, 3 rounds (150 total requests),
applied automatically unless overridden with `--num-requests`,
`--max-workers`, or `--num-rounds`.

**`--max-workers` auto-matching:** `--full-concurrency` matches
`--max-workers` to `--num-requests` so all requests fire at once, at any
level. Otherwise `--max-workers` stays at its conservative default of 3
and a warning is shown during the cost confirmation if
`max-workers < num-requests`. An explicit `--max-workers` always wins,
and `--ramp` ignores both since its stages set their own concurrency.

## Traffic Modes

**Flat** (default): `--num-requests 10` — fixed concurrency.
`--max-workers` defaults to 3; `--full-concurrency` matches it to
`--num-requests`. Set `--max-workers` explicitly to control concurrency:
`--num-requests 100 --max-workers 10` fires 100 requests, 10 at a time.
Flat mode output labels each iteration as a "round" (no stage numbers).

**Ramp-up**: `--ramp --stages 2,4,8,16` — escalating concurrency across
stages. Each stage fires N concurrent requests, waits for completion,
then moves to the next. Output labels each batch as `[STAGE N]`.

## Flags

| Flag                       | Default     | Description                                  |
|----------------------------|-------------|----------------------------------------------|
| `--agent`                  | hello_world | Agent name as registered in the server       |
| `--level`                  | norm        | Test depth: norm or adv for an all-in-one run (min is rejected there; min is used automatically by `--client-only`/`--server-only`) |
| `--server-log [PATH]`      | auto (local, norm/adv) | Server log analysis. Auto-detected for a local server at norm/adv; if not found you're prompted to continue without it (remote host aborts — use `--client-only`). Pass a path for an explicit file, or the flag alone to force auto-detect. |
| `--no-server-log`          | off         | Skip the missing-log prompt at norm/adv and run without server-log analysis; overrides the local auto-detect |
| `--no-tokens`              | off         | Disable per-request token accounting         |
| `--minimal`                | off         | Ask the server for the bare minimum of messages: only the final answer, cutting traffic and progress-event work — but it also drops the token-accounting message, so client-side LLM/token reporting is unavailable (tokens then come only from the server log) |
| `--profile-path`           | auto        | Directory containing profile JSON files (or `LOAD_TEST_PROFILE_PATH` env var) |
| `--fixtures-hocon-dir [DIR]` | off       | Build the whole profile (prompts, checks) from test-case hocon files in `DIR/<agent>/*.hocon`; the JSON profile is not read. Flag alone defaults to `tests/fixtures/load_tests`. See [Profiles from hocon files](#profiles-from-hocon-files) |
| `--host`                   | localhost   | Neuro-san server host                        |
| `--port`                   | 8080        | Neuro-san server port                        |
| `--num-requests`           | 3           | Requests per round in flat mode              |
| `--max-workers`            | 3             | Concurrent workers in flat mode. See `--full-concurrency` to match `--num-requests` |
| `--ramp`                   | off         | Enable ramp-up mode                          |
| `--stages`                 | 10,30,50,100| Concurrency per stage in ramp mode           |
| `--num-rounds`             | 1           | Repeat the full sequence N times             |
| `--max-requests`           | sum(stages) * num_rounds | Hard cap on total requests |
| `--request-timeout`        | 1200 (20m)  | Hard timeout per request. Accepts a bare number (seconds) or an `s`/`m`/`h` suffix (e.g. `90s`, `20m`, `2h`) |
| `--idle-timeout`           | 900 (15m)   | Abort a request that is idle for this long (no next stream chunk; resets on activity). Accepts seconds or an `s`/`m`/`h` suffix |
| `--stage-timeout`          | 1500 (25m)  | Hard timeout for entire stage/round. Accepts seconds or an `s`/`m`/`h` suffix. Kills remaining in-flight requests |
| `--total-timeout`          | 0 (disabled)| Hard timeout for entire load test. Accepts seconds or an `s`/`m`/`h` suffix. Kills run when exceeded |
| `--settle-time`            | 15 (15s)    | Wait after each stage for server cleanup. Accepts seconds or an `s`/`m`/`h` suffix |
| `--same-prompt`            | off         | Use identical prompt for all requests        |
| `--allow-caching`          | off         | Send pool prompts verbatim so caches can serve them. By default a unique `(request N)` suffix is appended to defeat caching |
| `--no-dry-run`             | off         | Skip the dry-run probe + cost confirmation (which run by default at min/norm; adv skips them already) |
| `--full-concurrency`       | off         | Match `--max-workers` to `--num-requests` so all fire at once |
| `--scale`                  | 1           | Multiply `--num-requests`, `--max-workers`, `--request-timeout`, `--idle-timeout`, `--stage-timeout`, `--total-timeout` by this factor. `--max-requests` auto-adjusts. |
| `--skip-reservation-check` | off         | Drop `reservation_id` from the required `success_fields` (servers without reservation storage) |
| `--https`                  | off         | Use HTTPS/TLS to reach the server; `--port` then defaults to 443 |
| `--client-only`            | off         | Split-machine: fire requests and monitor the client only; forces `min` |
| `--server-only`            | off         | Split-machine: monitor the server process/log only, fire nothing; forces `min` |
| `--archive-server-log`     | off         | Gzip the server log into the output directory after the run (requires `--server-log`) |
| `--output-dir`             | (none)      | Base directory for test output               |
| `--history-file PATH`      | `<output-base>/history.jsonl` | Append-only JSONL trend record, one row per client run |
| `--compare DIR`            | (none)      | Skip load test; scan DIR for previous runs and print a comparison table |
| `--compare-agent`, `--compare-baseline N`, `--compare-runs` | (none) | Filter `--compare` by agent, minimum request count (baseline), or folder names |
| `--trend PATH`             | (none)      | Skip load test; print one row per run from the history file, oldest first |
| `--rebuild DIR`, `--rebuild-all` | (none) | Reconstruct `raw_results.json` from the per-request files (e.g. after Ctrl+C); `--rebuild-all` redoes runs that already have one |
| `--project-root`           | (none)      | Project root for profile and hocon-fixture discovery |

### Abort on timeout

Any timeout aborts the entire test immediately and reports results
collected so far:

- **`--idle-timeout`**: A request receives no next stream chunk for N seconds → abort.
- **`--request-timeout`**: A request exceeds its hard time limit → abort. The request is abandoned as the response streams, so it stops within one streamed message of the limit rather than exactly at it; that wait is itself bounded by `--idle-timeout`.
- **`--stage-timeout`**: A stage/round exceeds its limit, remaining
  requests killed → abort.
- **`--total-timeout`**: Overall test elapsed time exceeded → abort
  before starting the next stage.
- **Server death**: The heartbeat detects the server process is no
  longer running (e.g. OOM kill) → abort.

On abort the test still runs the full reporting pipeline (latency
analysis, completion timeline, summary file, raw JSON) on whatever
results completed before the timeout.

### Memory monitoring

The heartbeat prints server RSS alongside thread counts on every
progress tick. The pre-run summary shows total and available system
RAM. The overall results section reports the peak server RSS observed
across all stages.

When server RSS exceeds 80% of total system RAM, a warning is printed:

```
  WARNING: Server RSS 12.8G / 16.0G (80%) — risk of OOM kill
```

## Environment Variables

| Variable                 | Effect                                     |
| ------------------------ | ------------------------------------------ |
| `OPENAI_API_BASE`        | **Aborts the run if set** (see below)      |
| `LOAD_TEST_PROFILE_PATH` | Default for `--profile-path`               |
| `PYTHONPATH`             | Repo root, so `tests.load_tests` imports   |

This test requires real LLM calls, so a set `OPENAI_API_BASE` is taken as
a mock environment and the run aborts before firing anything (a running
`mock_llm_server` process aborts it too). Unset it, or use
`load_test_mock_llm_service.py` for mock-based load testing.

## Pre-Run Summary and Dry-Run Probe

Before firing the full test, the load test displays a PRE-RUN SUMMARY.

**min / norm (default):** Fires 1 probe request to measure actual token
usage, cost, and response time, then shows estimated stage duration,
numbered warnings (if any), and asks the user to confirm. Pass `--no-dry-run`
to bypass the probe and confirmation.

**adv (default):** No dry-run probe — adv is treated as an explicit
stress test, so it shows the summary and runs immediately.

```
============================================================
  PRE-RUN SUMMARY
============================================================
  Agent:    agent_network_designer
  Level:    adv
  Requests: 50 x 3 rounds = 150 total
  Workers:  3 (concurrent)
  Timeouts: --request-timeout 1200s (20m) / --idle-timeout 900s (15m) / --stage-timeout 1500s (25m)
            --total-timeout disabled

  Running 1 dry-run probe to measure actual cost...

  Probe request completed in 30.2s (CREATED)
  Probe tokens: 500,000 (model: gpt-4o, cost: $0.2500)
  Estimated stage duration: ~1510s (30.2s x 50 requests)

  WARNINGS (3 found):
  1. Estimated cost exceeds $1:
     Probe used ~500,000 tokens ($0.25) x 150 requests = ~75,000,000 tokens (~$37.50)
     Model: gpt-4o
  2. --max-workers (3) < --num-requests (50): requests run in batches
  3. Estimated stage duration ~1510s exceeds --stage-timeout (1500s).
     Requests may be killed before completing.

  Tip: use --no-dry-run to skip this confirmation.
============================================================

Proceed with remaining 149 requests? [y/n]:
```

The probe result counts as request #0 of the first stage (not wasted).
If the user declines, only 1 request was consumed.

## Agent Profiles

Each agent needs a JSON profile at `tests/load_tests/prompts/profiles/`.
`--agent hello_world` loads `profiles/hello_world.json`. Prefixed agents
(e.g., `--agent basic/hello_world`) automatically resolve to the base
name (`hello_world.json`), so `--profile-path` is not required. Use `--profile-path` to point
to a custom directory (the filename is always derived from `--agent`).

```json
{
    "agent": "hello_world",
    "prompts": ["Hello, how are you today?", "What can you help me with?"],
    "estimated_tokens_per_request": 1000,
    "success_fields": [],
    "failure_patterns": [
        "No fully-specified LLM found",
        "API key to be set as an environment variable"
    ]
}
```

`success_fields`: fields that must come back non-empty in the response's
`sly_data` (or as `"field": "value"` in the answer text) for success.
Example: `["reservation_id", "agent_network_name"]` for
agent_network_designer — the request is marked FAILED if any are missing.

`failure_patterns`: substrings matched against the answer text to catch
server-side errors returned inside a successful HTTP 200 response
(e.g. missing API key).  When any pattern matches, the request is
downgraded from CREATED to FAILED.  The load test client does not
check for API keys itself — it communicates with the server over
HTTP, so keys are only needed on the server side.

### Profiles from hocon files

With `--fixtures-hocon-dir`, the JSON profile is not read at all: the
whole profile comes from test-case hocon files in `DIR/<agent>/*.hocon`,
in the same format the data-driven tests use
(`docs/test_case_hocon_reference.md`).

```bash
# Uses tests/fixtures/load_tests/hello_world/*.hocon
python -m tests.load_tests.load_test_cli --agent hello_world --fixtures-hocon-dir --client-only

# Custom parent directory: /my/fixtures/agent_network_designer/*.hocon
python -m tests.load_tests.load_test_cli --agent agent_network_designer --fixtures-hocon-dir /my/fixtures
```

The agent subfolder is derived from `--agent` (`basic/hello_world` →
`hello_world`). Each file holds exactly one interaction and yields one
prompt; every request is fired as an independent single-turn call.

`DIR` is the *parent* directory; do not include the agent folder. A
relative `DIR` is resolved against `--project-root` (or the current
directory), so use an absolute path for fixtures kept in another repo,
e.g. `--fixtures-hocon-dir /path/to/neuro-san-studio/tests/fixtures`.

```hocon
{
    "agent": "agent_network_designer",
    "failure_patterns": ["No fully-specified LLM found"],
    "interactions": [
        {
            "text": "Create an agent network for a pet grooming salon",
            "response": {
                "sly_data": {
                    "reservation_id": {},
                    "agent_network_name": {}
                }
            }
        }
    ]
}
```

| Hocon key | Becomes | Merged across files |
|---|---|---|
| `interactions[0].text` | one prompt | list, file order |
| `interactions[0].response.sly_data` keys | `success_fields` — each key must come back with a non-empty value | union |
| `failure_patterns` (optional) | `failure_patterns` | union |
| `estimated_tokens_per_request` (optional, reporting only) | `estimated_tokens_per_request` | max |

Only the *presence* of each `sly_data` key is checked today; the check
body (`keywords`, `value`, …) is reserved for a follow-up. The built-in
checks (request completed, non-empty answer, no failure pattern) always
apply.

The run aborts (exit 1) when the folder has no `*.hocon` files, a file's
`agent` does not match `--agent`, a file has more than one interaction,
`response.sly_data` is not a map, or no file has any text.
`raw_results.json` records `profile_source`, `fixtures_hocon_dir` and the
`hocon_files` list under `config`, and the pre-run `Config:` line shows
`profile_source=hocon (N files)`.

#### End-to-end example: agent_network_designer against a local Studio

Terminal 1 — serve the agent from a neuro-san-studio checkout, with
reservations enabled so each request returns a `reservation_id`:

```bash
cd <neuro-san-studio>
source venv/bin/activate                          # .env with the LLM API key
export NEURO_SAN_SERVER_HTTP_PORT=8080
export AGENT_NETWORK_DESIGNER_USE_RESERVATIONS=true
python -m neuro_san_studio run --server-only
# ready when: curl -s localhost:8080/api/v1/list | grep agent_network_designer
```

Terminal 2 — run the load test from this repo:

```bash
python -m tests.load_tests.load_test_cli \
  --agent agent_network_designer --fixtures-hocon-dir \
  --client-only --no-dry-run --num-requests 2 --max-workers 2 \
  --host localhost --port 8080 --output-dir /tmp/lt_ande
```

Expected: `LOAD TEST PASSED: all 2 requests completed successfully`, and
`/tmp/lt_ande/min/<run>/raw_results.json` lists each request as
`CREATED` with `agent_network_name` and `reservation_id` populated.
Without `AGENT_NETWORK_DESIGNER_USE_RESERVATIONS=true` the server returns
no `reservation_id`, so every request fails with `missing reservation_id`;
add `--skip-reservation-check` to waive that field on such a server.

## Output

Results go to `{tempdir}/load_test_{user}/{level}/{timestamp}_{requests}/`
by default (where `{tempdir}` is the system temp directory, e.g. `/tmp` on
Linux), or to the path specified by `--output-dir`. The base directory is
per-user because the temp directory is shared: a fixed `load_test` would
belong to whoever ran first, and everyone else would get
`PermissionError`. The request count is appended to the directory name
for quick identification:

```
/tmp/load_test_alice/adv/20260622_151428_50/
/tmp/load_test_alice/adv/20260622_151531_100/
/tmp/load_test_alice/adv/20260622_151648_150/
```

At `adv` level this includes:

| File                  | Contents                                         |
|-----------------------|--------------------------------------------------|
| `raw_results.json`    | All test data in a single JSON file              |
| `load_test.log`       | Full terminal output                             |
| `progress.log`        | All progress ticks and per-request CREATED results |
| `server_receipts.log` | Per-request server receipt details (with `--server-log`) |
| `server_tokens.log`   | Per-request token breakdown (when token data available) |
| `summary.txt`         | Human-readable summary (`adv` level only)        |
| `requests/`           | Raw stdout/stderr per request; failed HTTP requests write the exception traceback to `request_N_stderr.txt` |

### `raw_results.json`

Single source of truth for all test data. Feed it to an LLM to
generate Confluence reports, or load it in Python/pandas for custom
analysis.

Top-level keys:

| Key                       | Description                                          |
|---------------------------|------------------------------------------------------|
| `test_metadata`           | Timestamp, versions, platform, verdict, exit code    |
| `config`                  | All test parameters (agent, level, mode, timeouts)   |
| `aggregates`              | Totals: requests, tokens, cost, elapsed time         |
| `stage_summaries`         | Per-round results, retries, server counts, tokens    |
| `resource_rows`           | Server resource snapshots (before/after per round)   |
| `client_resource_rows`    | Client resource snapshots (before/peak/settled)      |
| `_schema`                 | Field descriptions for LLM self-service              |
| `_thresholds`             | Health benchmarks (warning/critical levels)          |
| `_analysis_hints`         | Diagnostic patterns to check                         |
| `_units`                  | Unit labels (seconds, MB, USD, etc.)                 |
| `_reporting_instructions` | Tells LLMs to report all checks, even clean ones     |

The `_`-prefixed keys are metadata for LLM-driven analysis. Upload
the JSON to ChatGPT/Claude/Gemini and say "analyze this" — no prompt
engineering needed.

Each stage summary contains:
- Per-request results (status, duration, start/end times, tokens,
  cost, model, errors)
- Server log data (retries, disconnections, amplification, server counts)
- Per-sub-network token breakdowns (`network_tokens`) when
  `--server-log` is provided — each entry has `network`, `llm_calls`,
  `total_tokens`, `prompt_tokens`, `completion_tokens`, `duration`,
  `cost`, and `model`

Resource rows contain server/client snapshots (RSS, threads, FDs, CPU)
captured before and after each round (flat mode) or stage (ramp mode).

## Latency Analysis

After each test run, a `LATENCY ANALYSIS` section reports LLM bottleneck
diagnostics:

### Request completion timeline

Shows cumulative request completion milestones per stage — answers
"how many requests came back after X time":

```
  Request completion timeline (Stage 1, 50 requests):
     50% (25 requests) completed by 12.1s
     60% (30 requests) completed by 14.3s
     70% (35 requests) completed by 16.8s
     80% (40 requests) completed by 19.2s
     90% (45 requests) completed by 22.5s
     95% (48 requests) completed by 26.1s
    100% (50 requests) completed by 30.2s
```

### Round-over-round degradation

Compares average latency at the same concurrency across rounds.
Increasing latency indicates LLM performance degradation under
sustained load:

```
  Latency degradation (round-over-round):
    50 concurrent: 12.8s -> 14.2s -> 16.1s (+26%)
```

### Concurrency timeline

Shows actual in-flight request count over time (ASCII chart). Reveals
whether the LLM serializes concurrent requests:

```
  Concurrency timeline (stage 1, round 1, 50 planned):
    Peak in-flight: 50
      0s |########################################| 50
     30s |################################        | 40
     60s |########################                | 30
```

### Summary file (`--level adv` only)

At `adv` level, a human-readable `summary.txt` is written to the
output directory. With `--no-dry-run` it is written automatically; without
`--no-dry-run` the user is prompted.

The summary includes per-request results, completion timeline, and
(when `--server-log` is provided) a per-request server timing
breakdown parsed from Start/Finish streaming_chat timestamps:

```
  request-1 (95.5s total):
    Client -> Server:     4.5s
    Server: agent_network_designer      90.8s
      ├─ agent_network_editor            19.7s
      ├─ agent_network_instructions_editor  44.4s
      └─ agent_network_query_generator    8.4s
    Server -> Client:     0.2s
```

## Cross-Run Comparison

Use `--compare` to scan a directory of previous runs and print a
side-by-side comparison table:

```bash
python -m tests.load_tests.load_test_cli --compare /tmp/load_test_alice/adv/
```

Output:

```
============================================================
  CROSS-RUN COMPARISON
============================================================
                    Folder  Requests  Wall Time  Avg/req  TTFR avg  Failed
-----------------------------------------------------------------------------------
  20260622_151428_50        50        1200s (20m)    24s      45s       0
  20260622_151531_100      100        3600s (60m)    36s      90s       2
  20260622_151648_150      150        6066s (101m)   40s     120s       8
```

No load test is executed — the command reads `raw_results.json` from
each subdirectory, extracts key metrics, and sorts by request count.

## Trend History

Use `--trend` to see repeated runs in the order they happened, which is
how a slowdown between neuro-san versions becomes visible:

```bash
python -m tests.load_tests.load_test_cli --trend /tmp/load_test_alice/adv/history.jsonl
```

Output:

```text
TREND HISTORY (/tmp/load_test_alice/adv/history.jsonl, 3 run(s))
       timestamp  neuro-san        agent    mode   via  reqs  done  <70s  <300s  ttfr    avg    wall  err  warn
---------------------------------------------------------------------------------------------------------------
2026-07-20 14:02     0.5.51  hello_world  client  http   200   200   181    200  2.1s  41.2s  612.0s    0     0
2026-07-24 09:15     0.5.52  hello_world  client  http   200   200   176    200  2.3s  44.8s  659.1s    0     0
2026-07-25 18:31     0.5.52  hello_world  client  http   200   188   120    188  3.9s  61.5s  812.7s    7     0
```

`PATH` may be the history file or a directory containing
`history.jsonl`, so the path printed at the end of a run works as-is.
Filter to one agent with `--compare-agent`.

Choose between the two views by the question being asked:

| Question                                          | Use         |
| ------------------------------------------------- | ----------- |
| How does the system behave as concurrency rises?  | `--compare` |
| Did the same load get slower than it used to be?  | `--trend`   |

Only `--trend` shows `neuro_san_version`, which `raw_results.json` does
not record. Server-only runs appear with `mode=server-only`, and their
`ttfr` is blank because a server log cannot measure the client's time to
first response.

## Exit Codes

- `0` — All requests completed successfully
- `1` — One or more requests failed, timed out, or were killed

## Code Quality

Conventions: one class per file, no standalone functions, `.get()` for
dict reads, `%`-formatting for logger calls, specific exception types,
named constants, TypedDicts (`RequestResult`, `StageSummary`, …) at data
boundaries, keyword-only arguments and explicit return types.

```bash
flake8 tests/load_tests
pylint tests/load_tests
python -m pytest tests/load_tests/unit -q
```

## Architecture

```
tests/load_tests/
  load_test_cli.py             LoadTestOrchestrator (main entry point)
  config.py                    Constants, TypedDicts, compiled patterns
  confirm.py                   Confirm (strict y/n prompt)
  cost_estimator.py            CostEstimator (per-model pricing)
  duration.py                  DurationParser (`90s`/`20m`/`2h` flag values)
  load_test_arguments.py       LoadTestArguments (argparse definitions)
  load_test_mock_llm_service.py  Mock-LLM load test (separate entry point)
  project_paths.py             ProjectPaths (project root / agent base name)

  monitoring/
    heartbeat.py               Heartbeat (progress + peak RSS tracking)
    resource_monitor.py        ResourceMonitor (psutil snapshots)
    server_log_monitor.py      ServerLogMonitor (log parsing)

  prompts/
    agent_profile.py           AgentProfile (data: prompts, success_fields, failure_patterns)
    agent_profile_factory.py   AgentProfileFactory (builds it from the JSON profile or hocon files)
    profiles/                  Per-agent JSON profiles

  reporting/
    disconnection_reporter.py  DisconnectionReporter
    json_metadata.py           JsonMetadata (self-documenting JSON)
    cross_run_comparison.py   CrossRunComparison (--compare output)
    latency_analyzer.py        LatencyAnalyzer (completion timeline, degradation)
    summary_file_writer.py     SummaryFileWriter (summary.txt output)
    pool_analyzer.py           PoolAnalyzer
    rebuild_results.py         RebuildResults (--rebuild)
    resource_reporter.py       ResourceReporter
    summary.py                 SummaryReporter
    system_resources.py        SystemResources (whole-system mem/cpu/threads)
    table_formatter.py         TableFormatter
    trend_history.py           TrendHistory (--trend output)

  traffic/
    http_client.py             HttpClient (in-thread HTTP streaming)
    output_parser.py           OutputParser (sly_data / token parsing)
    runner.py                  TrafficRunner (thread pool executor)

  validation/
    environment_validator.py   EnvironmentValidator (mock LLM, server)
    input_validator.py         InputValidator (stages, cost probe)
    output_validator.py        OutputValidator (results, retries)

  unit/                        Unit tests (python -m pytest tests/load_tests/unit)

tests/fixtures/load_tests/
  <agent>/*.hocon              Test-case hocons used with --fixtures-hocon-dir
```

## Notes

The `monitoring/` modules (`resource_monitor.py`, `server_log_monitor.py`,
`heartbeat.py`) use `psutil` and server log parsing as interim solutions.
These may be replaced by neuro-san built-in monitoring when available.
