# Load Test Framework

Fire concurrent requests at a neuro-san server, monitor resource usage,
and report results. Uses real LLM calls via `agent_cli` subprocesses.

## Prerequisites

- Python 3.11+
- `psutil` (`pip install psutil` or `pip install -r requirements.txt`)
- `OPENAI_API_KEY` set (real LLM calls = real API costs)
- A running neuro-san server

## Quick Start

Start the server:

```bash
cd /path/to/neuro-san-studio
source venv/bin/activate
export PYTHONPATH=$(pwd)
python -m neuro_san.service.main_loop.server_main_loop 2>&1 | tee logs/server.log
```

Run the load test (from neuro-san repo):

```bash
cd /path/to/neuro-san
export PYTHONPATH=$(pwd)

# Quick smoke test
python -m tests.load_tests.load_test --agent hello_world --level min --yes

# Standard load test with resource monitoring
python -m tests.load_tests.load_test --agent hello_world --level norm \
    --server-log /path/to/neuro-san-studio/logs/server.log --yes

# Full analysis with CSV, tokens, and recommendations
python -m tests.load_tests.load_test --agent hello_world --level adv \
    --ramp --stages 2,4,8 \
    --server-log /path/to/neuro-san-studio/logs/server.log --yes
```

## Test Levels (`--level`)

Controls the depth of analysis. Default is `norm`.

| Feature                              | min | norm | adv |
|--------------------------------------|-----|------|-----|
| Fire requests + validate responses   |  Y  |  Y   |  Y  |
| Save stdout/stderr for all requests  |  Y  |  Y   |  Y  |
| Server log (retries, disconnections) |     |  Y   |  Y  |
| Resource monitoring (RSS, threads)   |     |  Y   |  Y  |
| Token parsing and aggregates         |     |      |  Y  |
| Pool reuse analysis                  |     |      |  Y  |
| CSV export                           |     |      |  Y  |
| Recommendations + next-step command  |     |      |  Y  |

- **min**: Fast smoke test. Does the server respond under load?
- **norm**: How does the server behave? Monitors resources and retries.
- **adv**: Full analysis for reporting and capacity planning.

`--server-log` is required at `norm` and `adv` levels.

### Example: `--level min`

```
$ python -m tests.load_tests.load_test --agent hello_world --level min --yes

Level 'min': server monitoring and log reading disabled

Config: agent=hello_world, mode=flat, level=min, stages=[3], rounds=1,
  max_requests=100, host=localhost, port=8080, timeout=1200s

============================================================
  [STAGE 1] 3 concurrent connections
============================================================

Firing 3 concurrent hello_world requests... [20:49:27]

Request 1: CREATED (5.49s)
Request 2: CREATED (6.12s)
Request 3: CREATED (5.87s)

  Requests: 3
    Created: 3   Failed: 0   Timed out: 0   Killed: 0
  Duration: 6.12s | Avg: 5.83s per request

LOAD TEST PASSED: all 3 requests completed successfully
Output: /tmp/load_test/min/20260612_204927
```

### Example: `--level norm`

```
$ python -m tests.load_tests.load_test --agent hello_world --level norm \
    --server-log logs/server.log --yes

Config: agent=hello_world, mode=flat, level=norm, stages=[3], rounds=1,
  server_log=logs/server.log, settle_time=15s

============================================================
  [STAGE 1] 3 concurrent connections
============================================================
  Client BEFORE: RSS 17.7M, CPU 0.0%

Firing 3 concurrent hello_world requests... [20:49:51]  threads: 12

Request 1: CREATED (5.32s)
Request 2: CREATED (6.01s)
Request 3: CREATED (5.67s)

  Client SETTLED: RSS 17.9M (+0.2M from before)
  Waiting 15s for server cleanup...

  Requests: 3
    Created: 3   Failed: 0   Timed out: 0   Killed: 0
  Duration: 6.01s | Avg: 5.67s per request

LOAD TEST PASSED: all 3 requests completed successfully
Output: /tmp/load_test/norm/20260612_204951
```

### Example: `--level adv` with ramp-up

```
$ python -m tests.load_tests.load_test --agent hello_world --level adv \
    --ramp --stages 2,4 --server-log logs/server.log --yes

============================================================
  [STAGE 1] 2 concurrent connections
============================================================
  Client BEFORE: RSS 17.7M, CPU 0.0%

Firing 2 concurrent hello_world requests... [20:50:25]  threads: 12

Request 1: CREATED (5.49s)
Request 2: CREATED (6.12s)

  Client SETTLED: RSS 17.9M (+0.2M from before)
  Waiting 15s for server cleanup...

============================================================
  [STAGE 2] 4 concurrent connections
============================================================
  Client BEFORE: RSS 17.9M, CPU 0.0%

Firing 4 concurrent hello_world requests... [20:51:02]  threads: 14

Request 3: CREATED (7.21s)
Request 4: CREATED (8.03s)
Request 5: CREATED (7.54s)
Request 6: CREATED (7.89s)

  Client SETTLED: RSS 18.1M (+0.2M from before)
  Waiting 15s for server cleanup...

  Token usage (from server log):
    Req  Prompt  Completion  Total  Model
      1     520         490   1010  gpt-4
      2     510         500   1010  gpt-4
      3     530         480   1010  gpt-4
      4     515         505   1020  gpt-4
      5     525         495   1020  gpt-4
      6     518         502   1020  gpt-4

============================================================
  RECOMMENDATIONS
============================================================
  No issues detected at current load (6 requests, max 4 concurrent).

  Observations:
  * 6 completed, 0 failed, 0 timed out, 0 retries
  * Avg latency: 7.05s (per stage: 5.81s -> 7.67s)
  * Thread growth: +2 (12 -> 14)
  * Pool reuse: 0% -> 50%
  * Tokens: 6,090 total (avg 1,015/request), model: gpt-4

  Next step -- increase concurrency to find the server's capacity limit:
    python -m tests.load_tests.load_test --agent hello_world \
        --level adv --ramp --stages 4,8 --yes \
        --server-log logs/server.log

LOAD TEST PASSED: all 6 requests completed successfully
Output: /tmp/load_test/adv/20260612_205024
```

## Traffic Modes

Traffic patterns are independent of the test level.

**Flat mode** (default): Fixed concurrency, one stage.

```bash
--num-requests 10 --max-workers 5
```

**Ramp-up mode**: Escalating concurrency across stages.

```bash
--ramp --stages 2,4,8,16
```

Each stage fires N concurrent requests, waits for completion, then moves
to the next stage. Useful for finding the server's breaking point.

## Flags

| Flag                   | Default     | Description                                   |
|------------------------|-------------|-----------------------------------------------|
| `--agent`              | hello_world | Agent name as registered in the server         |
| `--level`              | norm        | Test depth: min, norm, or adv                  |
| `--server-log`         | (none)      | Path to server log file (required at norm/adv) |
| `--profile`            | auto        | Path to agent profile JSON                     |
| `--host`               | localhost   | Neuro-san server host                          |
| `--port`               | 8080        | Neuro-san server port                          |
| `--num-requests`       | 3           | Requests per stage in flat mode                |
| `--max-workers`        | 3           | Concurrent workers in flat mode                |
| `--ramp`               | off         | Enable ramp-up mode                            |
| `--stages`             | 10,30,50,100| Concurrency per stage in ramp mode             |
| `--num-rounds`         | 1           | Repeat the full sequence N times               |
| `--max-requests`       | 100         | Hard cap on total requests (cost safeguard)    |
| `--timeout`            | 1200        | Hard timeout per request (seconds)             |
| `--idle-timeout`       | 900         | Kill if no output for N seconds                |
| `--settle-time`        | 15          | Wait after each stage for server cleanup       |
| `--same-prompt`        | off         | Use identical prompt for all requests          |
| `--yes`                | off         | Skip the cost confirmation prompt              |
| `--skip-reservation-check` | off     | Skip reservation_id validation                 |
| `--project-root`       | (none)      | Project root for profile discovery             |

## Agent Profiles

Each agent needs a profile JSON at `tests/load_tests/prompts/profiles/`.
The `--agent` name maps to the filename (e.g., `--agent hello_world` loads
`profiles/hello_world.json`).

If the server registers the agent with a prefix (e.g., `basic/hello_world`),
use `--profile` to specify the file explicitly:

```bash
--agent basic/hello_world --profile tests/load_tests/prompts/profiles/hello_world.json
```

### Profile format

```json
{
    "agent": "hello_world",
    "prompts": [
        "Hello, how are you today?",
        "What can you help me with?"
    ],
    "estimated_tokens_per_request": 1000,
    "success_fields": []
}
```

| Field                         | Required | Description                              |
|-------------------------------|----------|------------------------------------------|
| `agent`                       | yes      | Agent name (for display)                 |
| `prompts`                     | yes      | Pool of prompts to send                  |
| `estimated_tokens_per_request`| no       | Used for cost estimation in confirmation |
| `success_fields`              | no       | Stdout fields that must be present       |

`success_fields` example: `["reservation_id", "agent_network_name"]` for
agent_network_designer. The load test parses these from agent_cli stdout
and marks the request as FAILED if any are missing.

## Output

Results are saved to `/tmp/load_test/{level}/{timestamp}/`:

```
/tmp/load_test/min/20260612_204816/
    load_test.log                   # Full console output
    requests/                       # Raw stdout/stderr per request

/tmp/load_test/norm/20260612_204900/
    load_test.log
    requests/

/tmp/load_test/adv/20260612_205024/
    load_test.log
    requests/
    results_per_request.csv         # Per-request data (status, duration, tokens)
    results_summary.csv             # Aggregated stats
    recommendations.txt             # Observations + suggested next command

/tmp/load_test/adv/resource_history.csv  # Cross-run resource history (appended)
```

## Exit Codes

- `0` — All requests completed successfully
- `1` — One or more requests failed, timed out, or were killed

## Validation

Every request is validated by:

1. **Exit code** — non-zero marks the request as FAILED
2. **Non-empty response** — empty stdout with exit code 0 is marked FAILED
3. **Success fields** — if the profile defines `success_fields`, they must
   appear in stdout

## Module Structure

```
tests/load_tests/
    config.py               # Constants (levels, statuses, timeouts)
    load_test.py             # Entry point and orchestrator
    monitoring/
        heartbeat.py         # Live server log watcher
        resource_monitor.py  # RSS, threads, FDs, CPU snapshots
        server_log_monitor.py# Retries, tokens, disconnections from server log
    prompts/
        agent_profile.py     # Profile loader
        profiles/            # Agent profile JSON files
    reporting/
        csv_export.py        # CSV output (per-request, summary, history)
        disconnection_report.py  # Server disconnection analysis
        pool_analysis.py     # Executor thread reuse tracking
        recommendations.py   # Observations + next-step suggestions
        resource_report.py   # Server and client resource tables
        summary.py           # Overall results and ramp-up summary
        table_utils.py       # Console table formatting
    traffic/
        cli_builder.py       # Build agent_cli subprocess commands
        process_monitor.py   # Idle timeout and hanging request detection
        runner.py            # ThreadPoolExecutor, fire requests, save output
    validation/
        environment.py       # API key, mock detection, server discovery
        input_validation.py  # Cost confirmation, stage resolution
        output_validation.py # Per-stage result logging
```

## CSV for Further Analysis

The CSV files are designed to be consumed by external tools or LLMs
for deeper investigation beyond what the load test reports directly.
Feed the CSVs into an LLM to analyze latency patterns, token cost
breakdowns, cross-run comparisons, or degradation trends.

## Notes

The `monitoring/` modules (`resource_monitor.py`, `server_log_monitor.py`,
`heartbeat.py`) use `psutil` and server log parsing as interim solutions
for resource monitoring, retry detection, and progress tracking. These may
be replaced by neuro-san's built-in monitoring and telemetry when those
features become available.
