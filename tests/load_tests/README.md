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

# Smoke test with resource monitoring (no server log needed)
python -m tests.load_tests.load_test --agent hello_world --level min \
    --monitor-resources --yes

# Standard — with resource monitoring and server log
python -m tests.load_tests.load_test --agent hello_world --level norm \
    --server-log /path/to/logs/server.log --yes

# Standard — without server log (resources + tokens)
python -m tests.load_tests.load_test --agent hello_world --level norm --yes

# Full analysis — with server log
python -m tests.load_tests.load_test --agent hello_world --level adv \
    --ramp --stages 2,4,8 \
    --server-log /path/to/logs/server.log --yes

# Full analysis — without server log (CSV + tokens, no retries)
python -m tests.load_tests.load_test --agent hello_world --level adv \
    --ramp --stages 2,4,8 --yes
```

## Test Levels (`--level`)

| Feature                              | min | norm | adv |
|--------------------------------------|-----|------|-----|
| Fire requests + validate responses   |  Y  |  Y   |  Y  |
| Server log (retries, disconnections) |     | opt  | opt |
| Resource monitoring (RSS, threads)   | opt |  Y   |  Y  |
| Token accounting (from stdout)       | opt |  Y   |  Y  |
| Pool reuse analysis                  |     |      | opt |
| CSV export                           |     |      |  Y  |
| Recommendations + next-step command  |     |      |  Y  |

`opt` = available with optional flags. `--server-log` enables retry
counting, server-side validation, disconnection detection, and pool
reuse analysis at any level. `--monitor-resources` enables psutil
monitoring at `min` level. `--include-tokens` enables per-request
token accounting via `agent_cli --tokens` at `min` level (auto-enabled
at `norm` and `adv`).

When `--server-log` is omitted, server-log-dependent sections print
"not available" in the output.

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
| `--server-log`             | (none)      | Path to server log file (optional)           |
| `--monitor-resources`      | off         | Enable psutil monitoring at min level         |
| `--include-tokens`         | off         | Capture token accounting from agent_cli      |
| `--profile`                | auto        | Path to agent profile JSON                   |
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
| `--yes`                    | off         | Skip the cost confirmation prompt            |
| `--skip-reservation-check` | off         | Skip reservation_id validation               |
| `--project-root`           | (none)      | Project root for profile discovery           |

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
includes:

| File                      | Contents                                    |
|---------------------------|---------------------------------------------|
| `results_per_request.csv` | One row per request: status, duration, tokens, cost, retries, disconnections |
| `results_resources.csv`   | One row per stage: server/client RSS, threads, FDs, CPU, wall clock, test config |
| `recommendations.txt`     | Analysis and next-step suggestions           |
| `load_test.log`           | Full terminal output                         |
| `requests/`               | Raw stdout/stderr per request                |

### CSV schema: `results_per_request.csv`

Core: `run_id, timestamp, agent, stage, round, request_id, status,
duration_sec, prompt, error`

Tokens: `total_tokens, prompt_tokens, completion_tokens, llm_calls,
model, cost_usd`

Server log: `total_retries, disconnected` (empty when no `--server-log`)

Any agent-specific parsed fields (e.g., `reservation_id`) are appended
as additional columns.

### CSV schema: `results_resources.csv`

Server: `server_before_rss, server_settled_rss, server_rss_delta,
server_before_threads, server_peak_threads, server_settled_threads,
server_thread_delta, server_fds, server_conns, server_cpu,
server_children`

Client: `client_before_rss, client_peak_rss, client_settled_rss,
client_rss_delta, client_cpu, client_fds, client_threads`

Server log: `total_retries, amplification, primary_started,
primary_finished, total_started, total_finished, disconnections`
(empty when no `--server-log`)

Config: `mode, max_workers, timeout, idle_timeout, settle_time`

These CSVs contain all data needed to generate the Confluence load
test report without re-running the test.

## Exit Codes

- `0` — All requests completed successfully
- `1` — One or more requests failed, timed out, or were killed

## Notes

The `monitoring/` modules (`resource_monitor.py`, `server_log_monitor.py`,
`heartbeat.py`) use `psutil` and server log parsing as interim solutions.
These may be replaced by neuro-san built-in monitoring when available.
