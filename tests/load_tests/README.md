# Load Test Framework

Fire concurrent requests at a neuro-san server, monitor resource usage,
and report results. Uses real LLM calls via `agent_cli` subprocesses.

## Contents

- [Quick Start](#quick-start)
- [Test Levels](#test-levels---level)
- [Traffic Modes](#traffic-modes)
- [Flags](#flags)
- [Pre-Run Summary and Dry-Run Probe](#pre-run-summary-and-dry-run-probe)
- [Agent Profiles](#agent-profiles)
- [Output](#output)
- [Latency Analysis](#latency-analysis)
- [Exit Codes](#exit-codes)
- [Code Quality](#code-quality)
- [Architecture](#architecture)
- [Notes](#notes)

## Quick Start

Start the server (from neuro-san-studio):

```bash
export PYTHONPATH=$(pwd)
python -m neuro_san.service.main_loop.server_main_loop 2>&1 | tee logs/server.log
```

Run the load test (from neuro-san):

```bash
export PYTHONPATH=$(pwd)

# Smoke test — does the server respond?
python -m tests.load_tests.load_test --agent hello_world --level min --yes

# Smoke test with resource monitoring (no server log needed)
python -m tests.load_tests.load_test --agent hello_world --level min \
    --monitor-resources --yes

# Standard — with server log (auto-detect from server process)
python -m tests.load_tests.load_test --agent hello_world --level norm \
    --server-log --yes

# Standard — with server log (explicit path)
python -m tests.load_tests.load_test --agent hello_world --level norm \
    --server-log /path/to/logs/server.log --yes

# Standard — without server log (resources + tokens)
python -m tests.load_tests.load_test --agent hello_world --level norm --yes

# Full analysis — with server log
python -m tests.load_tests.load_test --agent hello_world --level adv \
    --ramp --stages 2,4,8 \
    --server-log /path/to/logs/server.log --yes

# Full analysis — without server log (JSON + tokens, no retries)
python -m tests.load_tests.load_test --agent hello_world --level adv \
    --ramp --stages 2,4,8 --yes
```

## Test Levels (`--level`)

| Feature                              | min | norm | adv |
|--------------------------------------|-----|------|-----|
| Fire requests + validate responses   |  Y  |  Y   |  Y  |
| Server log (retries, disconnections) |     | opt  | opt |
| Resource monitoring (RSS, threads)   | opt |  Y   |  Y  |
| Token accounting (from stdout)       |  Y  |  Y   |  Y  |
| Pool reuse analysis                  |     |      | opt |
| JSON export (`raw_results.json`)     |  Y  |  Y   |  Y  |

`opt` = available with optional flags. `--server-log` enables retry
counting, server-side validation, disconnection detection, and pool
reuse analysis at any level.  Use `--server-log` alone to auto-detect
the log from the server process, or `--server-log <path>` for an
explicit file. `--monitor-resources` enables psutil monitoring at
`min` level. Token accounting via `agent_cli --tokens` is enabled
at all levels by default (disable with `--no-tokens`).

**`adv` level defaults:** 50 requests, 3 rounds (150 total requests).
With `--yes`, workers auto-match to 50 (full concurrency). Without
`--yes`, workers default to 3 with a warning. These are applied
automatically unless overridden with `--num-requests`, `--max-workers`,
or `--num-rounds`.

**`--max-workers` auto-matching:** At adv level with `--yes` (power
user mode), `--max-workers` auto-matches `--num-requests` so all
requests fire concurrently. At other levels or without `--yes`,
`--max-workers` defaults to 3 (conservative). A warning is shown
during the cost confirmation on all levels if
`max-workers < num-requests`. Explicit `--max-workers` is always
respected regardless of `--yes`.

When `--server-log` is omitted, server-log-dependent sections print
"not available" in the output.  When `--server-log` is passed without
a path and auto-detection fails, the load test aborts with an error
and suggests providing the path explicitly.

## Traffic Modes

**Flat** (default): `--num-requests 10` — fixed concurrency.
`--max-workers` defaults to 3; at adv level with `--yes` it auto-matches
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
| `--level`                  | norm        | Test depth: min, norm, or adv                |
| `--server-log [PATH]`      | (none)      | Enable server log analysis. Without a path, auto-detects from server process. With a path, uses the given file. |
| `--monitor-resources`      | off         | Enable psutil monitoring at min level         |
| `--no-tokens`              | off         | Disable per-request token accounting         |
| `--profile-path`           | auto        | Directory containing profile JSON files (or `LOAD_TEST_PROFILE_PATH` env var) |
| `--host`                   | localhost   | Neuro-san server host                        |
| `--port`                   | 8080        | Neuro-san server port                        |
| `--num-requests`           | 3           | Requests per round in flat mode              |
| `--max-workers`            | 3             | Concurrent workers in flat mode. At adv + `--yes`, auto-matches `--num-requests` |
| `--ramp`                   | off         | Enable ramp-up mode                          |
| `--stages`                 | 10,30,50,100| Concurrency per stage in ramp mode           |
| `--num-rounds`             | 1           | Repeat the full sequence N times             |
| `--max-requests`           | sum(stages) * num_rounds | Hard cap on total requests |
| `--request-timeout`        | 1200        | Hard timeout per request (seconds)           |
| `--idle-timeout`           | 900         | Kill if no `agent_cli` output for N seconds (resets on activity) |
| `--stage-timeout`          | 1500        | Hard timeout for entire stage/round (seconds). Kills remaining in-flight requests |
| `--total-timeout`          | 0 (disabled)| Hard timeout for entire load test (seconds). Kills run when exceeded |
| `--settle-time`            | 15          | Wait after each stage for server cleanup     |
| `--same-prompt`            | off         | Use identical prompt for all requests        |
| `--yes`                    | off         | Skip cost confirmation (adv only). Auto-matches `--max-workers` to `--num-requests` |
| `--scale`                  | 1           | Multiply `--num-requests`, `--max-workers`, `--request-timeout`, `--idle-timeout`, `--stage-timeout`, `--total-timeout` by this factor. `--max-requests` auto-adjusts. |
| `--skip-reservation-check` | off         | Skip reservation_id validation               |
| `--output-dir`             | (none)      | Base directory for test output               |
| `--project-root`           | (none)      | Project root for profile discovery           |

## Pre-Run Summary and Dry-Run Probe

Before firing the full test, the load test displays a PRE-RUN SUMMARY.

**With `--yes` (adv only):** Shows the summary with any applicable
warnings and runs immediately (no probe).

**Without `--yes`:** Fires 1 probe request to measure actual token
usage, cost, and response time.  Then shows estimated stage duration,
numbered warnings (if any), and asks the user to confirm:

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

  Tip: use --yes at adv level to skip this confirmation.
============================================================

Proceed with remaining 149 requests? [y/N]:
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

`success_fields`: stdout fields that must be present for success.
Example: `["reservation_id", "agent_network_name"]` for
agent_network_designer — the request is marked FAILED if any are missing.

`failure_patterns`: substrings matched against stdout to catch
server-side errors returned inside a successful HTTP 200 response
(e.g. missing API key).  When any pattern matches, the request is
downgraded from CREATED to FAILED.  The load test client does not
check for API keys itself — it communicates with the server over
HTTP, so keys are only needed on the server side.

## Output

Results go to `{tempdir}/load_test/{level}/{timestamp}/` by default
(where `{tempdir}` is the system temp directory, e.g. `/tmp` on Linux),
or to the path specified by `--output-dir`. At `adv` level this includes:

| File                  | Contents                                         |
|-----------------------|--------------------------------------------------|
| `raw_results.json`    | All test data in a single JSON file              |
| `load_test.log`       | Full terminal output                             |
| `requests/`           | Raw stdout/stderr per request                    |

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
| `_schema`                 | 38 field descriptions for LLM self-service           |
| `_thresholds`             | 16 health benchmarks (warning/critical levels)       |
| `_analysis_hints`         | 10 diagnostic patterns to check                      |
| `_units`                  | 16 unit labels (seconds, MB, USD, etc.)              |
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
output directory. With `--yes` it is written automatically; without
`--yes` the user is prompted.

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

## Exit Codes

- `0` — All requests completed successfully
- `1` — One or more requests failed, timed out, or were killed

## Code Quality

This framework follows three review playbooks:

- **Code_Fink (Dan):** One class per file, `.get()` for dict reads,
  `.update()` for dict writes, no standalone functions, `%`-formatting
  for logger calls, specific exception types, named constants for
  magic numbers.

- **Code_Francon (Olivier):** Silent `except/pass` blocks log via
  `logger.debug`, `CostEstimator` extracted to its own file, README
  documents all flags including `--output-dir`.

- **Code_Sargent (Darren):** TypedDicts (`RequestResult`,
  `StageSummary`, `StatusCounts`, `ServerCounts`, `TokenEntry`,
  `NetworkTokenEntry`, `ResourceSnapshot`) replace `Dict[str, Any]`
  at data boundaries. Keyword-only arguments (`*`) eliminate all
  `too-many-positional-arguments` warnings. Explicit return type
  annotations on every method.

- **Copilot:** Empty-prompts validation in `AgentProfile`,
  signed delta formatting (no more `+-3.0M`), Windows compatibility
  fallbacks (`num_fds`/`select.select`/closed-pipe guards/temp dir),
  clean error on invalid `--stages`, `ServerCounts` partial TypedDict,
  auto-resolve profile from agent name, `--max-workers` auto-matches
  `--num-requests` at adv + `--yes`, `adv` level defaults (50×3),
  `--yes` restricted to adv level, flat mode hides stage labels and
  uses round-based output, PRE-RUN SUMMARY with numbered warnings
  and estimated stage duration.

Lint status: flake8 clean, pylint 10.00/10.

## Architecture

```
tests/load_tests/
  load_test.py                 LoadTestOrchestrator (main entry point)
  config.py                    Constants, TypedDicts, compiled patterns
  cost_estimator.py            CostEstimator (per-model pricing)

  monitoring/
    heartbeat.py               Heartbeat (progress + peak RSS tracking)
    resource_monitor.py        ResourceMonitor (psutil snapshots)
    server_log_monitor.py      ServerLogMonitor (log parsing)

  prompts/
    agent_profile.py           AgentProfile (prompt/validation config)
    profiles/                  Per-agent JSON profiles

  reporting/
    disconnection_reporter.py  DisconnectionReporter
    json_metadata.py           JsonMetadata (self-documenting JSON)
    latency_analyzer.py        LatencyAnalyzer (completion timeline, degradation)
    summary_file_writer.py     SummaryFileWriter (summary.txt output)
    pool_analyzer.py           PoolAnalyzer
    resource_reporter.py       ResourceReporter
    summary.py                 SummaryReporter
    table_formatter.py         TableFormatter

  traffic/
    cli_builder.py             CliBuilder (agent_cli commands)
    process_monitor.py         ProcessMonitor (subprocess lifecycle)
    runner.py                  TrafficRunner (thread pool executor)

  validation/
    environment_validator.py   EnvironmentValidator (mock LLM, server)
    input_validator.py         InputValidator (stages, cost probe)
    output_validator.py        OutputValidator (results, retries)
```

## Notes

The `monitoring/` modules (`resource_monitor.py`, `server_log_monitor.py`,
`heartbeat.py`) use `psutil` and server log parsing as interim solutions.
These may be replaced by neuro-san built-in monitoring when available.
