# Load Test Framework

Fire concurrent requests at a neuro-san server, monitor resource usage,
and report results. Uses real LLM calls via `agent_cli` subprocesses.

## Contents

- [Quick Start](#quick-start)
- [Test Levels](#test-levels---level)
- [Traffic Modes](#traffic-modes)
- [Flags](#flags)
- [Agent Profiles](#agent-profiles)
- [Output](#output)
- [Exit Codes](#exit-codes)
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

# Standard — with resource monitoring
python -m tests.load_tests.load_test --agent hello_world --level norm \
    --server-log /path/to/logs/server.log --yes

# Full analysis — ramp-up with CSV, tokens, recommendations
python -m tests.load_tests.load_test --agent hello_world --level adv \
    --ramp --stages 2,4,8 \
    --server-log /path/to/logs/server.log --yes
```

## Test Levels (`--level`)

| Feature                              | min | norm | adv |
|--------------------------------------|-----|------|-----|
| Fire requests + validate responses   |  Y  |  Y   |  Y  |
| Server log (retries, disconnections) |     |  Y   |  Y  |
| Resource monitoring (RSS, threads)   |     |  Y   |  Y  |
| Token parsing and aggregates         |     |      |  Y  |
| Pool reuse analysis                  |     |      |  Y  |
| CSV export                           |     |      |  Y  |
| Recommendations + next-step command  |     |      |  Y  |

`--server-log` is required at `norm` and `adv` levels.

## Traffic Modes

**Flat** (default): `--num-requests 10 --max-workers 5` — fixed concurrency.

**Ramp-up**: `--ramp --stages 2,4,8,16` — escalating concurrency across
stages. Each stage fires N concurrent requests, waits for completion,
then moves to the next.

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

Each agent needs a JSON profile at `tests/load_tests/prompts/profiles/`.
`--agent hello_world` loads `profiles/hello_world.json`. If the server
registers the agent with a prefix (e.g., `basic/hello_world`), use
`--profile` to point to the file explicitly.

```json
{
    "agent": "hello_world",
    "prompts": ["Hello, how are you today?", "What can you help me with?"],
    "estimated_tokens_per_request": 1000,
    "success_fields": []
}
```

`success_fields` example: `["reservation_id", "agent_network_name"]` for
agent_network_designer — the request is marked FAILED if any are missing.

## Output

Results go to `/tmp/load_test/{level}/{timestamp}/`. At `adv` level this
includes `results_per_request.csv`, `results_summary.csv`, and
`recommendations.txt`. A cross-run `resource_history.csv` is appended at
`/tmp/load_test/adv/`.

The CSV files can be fed into an LLM or analysis tool for deeper
investigation (latency patterns, token costs, cross-run comparisons).

## Exit Codes

- `0` — All requests completed successfully
- `1` — One or more requests failed, timed out, or were killed

## Notes

The `monitoring/` modules (`resource_monitor.py`, `server_log_monitor.py`,
`heartbeat.py`) use `psutil` and server log parsing as interim solutions.
These may be replaced by neuro-san built-in monitoring when available.
