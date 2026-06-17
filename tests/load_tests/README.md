# Load Test Framework

Fire concurrent requests at a neuro-san server, monitor resource usage,
and report results. Uses real LLM calls via `agent_cli` subprocesses.

## Contents

- [Quick Start](#quick-start)
- [Test Levels](#test-levels---level)
- [Traffic Modes](#traffic-modes)
- [Flags](#flags)
- [Cost Confirmation and Dry-Run Probe](#cost-confirmation-and-dry-run-probe)
- [Agent Profiles](#agent-profiles)
- [Output](#output)
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

**`adv` level defaults:** 50 requests, 50 workers, 3 rounds (150 total
requests). These are applied automatically unless overridden with
`--num-requests`, `--max-workers`, or `--num-rounds`.

When `--server-log` is omitted, server-log-dependent sections print
"not available" in the output.  When `--server-log` is passed without
a path and auto-detection fails, the load test aborts with an error
and suggests providing the path explicitly.

## Traffic Modes

**Flat** (default): `--num-requests 10 --max-workers 5` — fixed concurrency.

**Ramp-up**: `--ramp --stages 2,4,8,16` — escalating concurrency across
stages. Each stage fires N concurrent requests, waits for completion,
then moves to the next.

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
| `--num-requests`           | 3           | Requests per stage in flat mode              |
| `--max-workers`            | 3           | Concurrent workers in flat mode              |
| `--ramp`                   | off         | Enable ramp-up mode                          |
| `--stages`                 | 10,30,50,100| Concurrency per stage in ramp mode           |
| `--num-rounds`             | 1           | Repeat the full sequence N times             |
| `--max-requests`           | 100 (flat) / sum(stages) * num_rounds (ramp) | Hard cap on total requests |
| `--timeout`                | 1200        | Hard timeout per request (seconds)           |
| `--idle-timeout`           | 900         | Kill if no output for N seconds              |
| `--settle-time`            | 15          | Wait after each stage for server cleanup     |
| `--same-prompt`            | off         | Use identical prompt for all requests        |
| `--yes`                    | off         | Skip dry-run probe and cost confirmation     |
| `--skip-reservation-check` | off         | Skip reservation_id validation               |
| `--output-dir`             | (none)      | Base directory for test output               |
| `--project-root`           | (none)      | Project root for profile discovery           |

## Cost Confirmation and Dry-Run Probe

Before firing the full test, the load test shows a cost warning.

**With `--yes`:** Shows the warning and runs immediately (no probe).

**Without `--yes`:** Fires 1 probe request with `--tokens` to measure
actual token usage and cost, then asks the user to confirm:

```
Running 1 dry-run probe to measure actual cost...
Request 1: CREATED (22.8s)
  Probe result: CREATED in 22.8s
  Probe tokens: 2,158 (model: gpt-5.2-2025-12-11, cost: $0.011342)
  Estimated total for 10 requests: ~21,580 tokens (~$0.1134)

Proceed with remaining 9 requests? [y/N]:
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
- Per-request results (status, duration, tokens, cost, model, errors)
- Server log data (retries, disconnections, amplification, server counts)
- Per-sub-network token breakdowns (`network_tokens`) when
  `--server-log` is provided — each entry has `network`, `llm_calls`,
  `total_tokens`, `prompt_tokens`, `completion_tokens`, `duration`,
  `cost`, and `model`

Resource rows contain server/client snapshots (RSS, threads, FDs, CPU)
captured before and after each stage.

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
  auto-resolve profile from agent name.

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
