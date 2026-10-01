# Load Test

Send many requests at once to a neuro-san server and see how it holds up:
how many requests succeed, how long they take, how many tokens they cost,
and how much memory the server uses.

The load test makes real LLM calls, so every run costs money. By default it
sends one probe request first, shows the estimated cost, and asks before
sending the rest (`adv` skips this).

## Before you start

- A neuro-san server serving the agent you want to test, with its LLM API
  key set. The load test itself needs no API key.
- A neuro-san-studio checkout for the server commands below.
- A neuro-san checkout for the load-test commands. Run them from its root, after:

  ```bash
  export PYTHONPATH=$(pwd)
  ```

- `OPENAI_API_BASE` must not be set (see [Troubleshooting](#troubleshooting)).

## Quick start

Terminal 1, from a neuro-san-studio checkout, start the server and keep its log:

```bash
mkdir -p logs
python -m neuro_san_studio run --server-only 2>&1 | tee logs/server.log
```

Terminal 2, from neuro-san, check that the server answers:

```bash
python -m tests.load_tests.load_test_cli --agent hello_world --client-only
```

It sends one probe request, shows the estimated cost, and asks before going on.
A good run ends with `LOAD TEST PASSED`. Results are saved under
`/tmp/load_test_<you>/` (see [Results](#results)).

## Common runs

```bash
# Standard run (server on this machine, log found automatically)
python -m tests.load_tests.load_test_cli --agent hello_world --level norm

# Standard run, server log at a known path
python -m tests.load_tests.load_test_cli --agent hello_world --level norm \
    --server-log /path/to/logs/server.log

# 100 requests, 10 at a time
python -m tests.load_tests.load_test_cli --agent hello_world \
    --num-requests 100 --max-workers 10

# Step up the load: 2, then 4, then 8 requests at once
python -m tests.load_tests.load_test_cli --agent hello_world --level adv \
    --ramp --stages 2,4,8

# Remote server (no server log): client side only
python -m tests.load_tests.load_test_cli --agent hello_world --client-only \
    --host my-server.example.com --https
```

Add `--no-dry-run` to skip the probe and the cost question (for scripts and CI).

### Server and client on different machines

Run the same command on both machines, one with `--server-only` (watches
the server process and log, sends nothing) and one with `--client-only`
(sends the requests and watches the client).

### Example: agent_network_designer against a local Studio

Terminal 1, from neuro-san-studio (reservations on, so each request returns
a `reservation_id`):

```bash
export NEURO_SAN_SERVER_HTTP_PORT=8080
export AGENT_NETWORK_DESIGNER_USE_RESERVATIONS=true
python -m neuro_san_studio run --server-only
# ready when: curl -s localhost:8080/api/v1/list | grep agent_network_designer
```

Terminal 2, from neuro-san:

```bash
python -m tests.load_tests.load_test_cli \
  --agent agent_network_designer --fixtures-hocon-dir \
  --client-only --no-dry-run --num-requests 2 --max-workers 2 \
  --output-dir /tmp/lt_ande
```

Expected: `LOAD TEST PASSED: all 2 requests completed successfully`.
Without `AGENT_NETWORK_DESIGNER_USE_RESERVATIONS=true` every request fails
with `sly_data.agent_reservations: ... is None`.

## Test levels

Pick how much the run measures with `--level`:

| What you get                                    | `norm` (default) | `adv` |
|-------------------------------------------------|:----:|:---:|
| Pass/fail per request, timings, tokens, cost    |  Y   |  Y  |
| Server memory and threads                       |  Y   |  Y  |
| Retries and disconnections (needs server log)   |  Y   |  Y  |
| `summary.txt` report                            |      |  Y  |
| Probe + cost question before the run            |  Y   |     |
| Defaults: 50 requests x 3 rounds                |      |  Y  |

`--client-only` and `--server-only` use a lighter level, `min`, on their own.

**Server log.** For a server on the same machine the log is found
automatically. If it can't be found, you are asked whether to go on
without it. Use `--server-log PATH` to give the file, or `--no-server-log`
to skip it.

## Prompts and checks

Each prompt and the checks on its answer come from test-case hocon files,
one file per prompt, in `<dir>/<agent>/*.hocon`. Turn this on with
`--fixtures-hocon-dir`; on its own it uses `tests/fixtures/load_tests`.

```bash
# tests/fixtures/load_tests/hello_world/*.hocon
python -m tests.load_tests.load_test_cli --agent hello_world --fixtures-hocon-dir --client-only

# /my/fixtures/agent_network_designer/*.hocon
python -m tests.load_tests.load_test_cli --agent agent_network_designer \
    --fixtures-hocon-dir /my/fixtures
```

Give the parent folder, not the agent folder. For fixtures in another repo,
use an absolute path.

A file looks like this:

```hocon
{
    "agent": "agent_network_designer",
    "failure_patterns": ["No fully-specified LLM found"],
    "interactions": [
        {
            "text": "Create an agent network for a pet grooming salon",
            "response": {
                "sly_data": {
                    "agent_network_name": { "not_value": "" },
                    "agent_reservations": { "not_value": "" }
                }
            }
        }
    ]
}
```

- `text`: the prompt.
- `response`: what the answer must contain, using `keywords`, `not_keywords`,
  `value`, `not_value`, `gist` and the other checks in
  [test_case_hocon_reference.md](../../docs/test_case_hocon_reference.md).
  `{ "not_value": "" }` means "present and not empty"; an empty `{}` checks nothing.
- `failure_patterns` (optional): text that marks a request as failed even
  when the server answered, e.g. a missing API key message.
- One interaction per file. Only top-level `sly_data` keys can be checked
  (`agent_reservations`, not `agent_reservations[0].reservation_id`).

Without `--fixtures-hocon-dir`, prompts come from
`tests/load_tests/prompts/profiles/<agent>.json` (being phased out).

## Results

Each run gets its own folder, `/tmp/load_test_<you>/<level>/<time>_<host>_<requests>/`
(or under `--output-dir`):

| File                  | What's in it                                  |
|-----------------------|-----------------------------------------------|
| `raw_results.json`    | Everything from the run                       |
| `summary.txt`         | Readable report (`adv` only)                  |
| `stdout.log`          | Everything printed on screen                  |
| `progress.log`        | Progress ticks and each finished request      |
| `server_receipts.log` | Per-request server details (with server log)  |
| `server_tokens.log`   | Per-request token breakdown                   |
| `requests/`           | Output of each request; errors in `request_N_stderr.txt` |

`raw_results.json` describes its own fields, so you can load it in Python/pandas or hand it to an LLM.

At the end of each run you also get:

- **Completion timeline**: how many requests had come back by when.
- **Round-over-round latency**: whether the same load got slower each round.
- **Concurrency chart**: how many requests were really in flight over time.
- **Per-request breakdown** in `summary.txt` (with server log): time spent
  in each sub-agent.

The command exits with `0` when every request succeeded and `1` otherwise.

## Comparing runs

```bash
# Side by side, sorted by request count: "how does it behave as load grows?"
python -m tests.load_tests.load_test_cli --compare /tmp/load_test_<you>/adv/

# In time order: "did the same load get slower than before?"
python -m tests.load_tests.load_test_cli --trend /tmp/load_test_<you>/adv/history.jsonl
```

Neither command sends any requests. `--trend` also shows the neuro-san
version of each run. Add `--compare-agent NAME` to show one agent only.

## Options

Durations accept seconds or `s`/`m`/`h`, e.g. `90s`, `20m`, `2h`.

### What to test

| Option | Default | Meaning |
|---|---|---|
| `--agent` | hello_world | Agent to test |
| `--level` | norm | `norm` or `adv`, see [Test levels](#test-levels) |
| `--fixtures-hocon-dir [DIR]` | off | Prompts and checks from hocon files |
| `--profile-path` | auto | Folder of JSON profiles (or `LOAD_TEST_PROFILE_PATH`) |
| `--project-root` | `PYTHONPATH` | Where relative fixture/profile paths start |

### Where the server is

| Option | Default | Meaning |
|---|---|---|
| `--host` | localhost | Server host |
| `--port` | 8080 | Server port (443 with `--https`) |
| `--https` | off | Use HTTPS |
| `--server-log [PATH]` | auto | Server log to analyze |
| `--no-server-log` | off | Run without the server log |
| `--client-only` / `--server-only` | off | Split client and server across machines |

### How much load

| Option | Default | Meaning |
|---|---|---|
| `--num-requests` | 3 | Requests per round |
| `--max-workers` | 3 | Requests in flight at once |
| `--full-concurrency` | off | Send a whole round at once (unless `--max-workers` is given; not with `--ramp`) |
| `--num-rounds` | 1 | Repeat the whole run N times |
| `--ramp`, `--stages` | off, 10,30,50,100 | Step up the load, one stage per value |
| `--max-requests` | all stages x rounds | Upper limit on total requests |
| `--scale` | 1 | Multiply requests, workers and timeouts |
| `--same-prompt` | off | Send the same prompt every time |
| `--allow-caching` | off | Don't make prompts unique (by default `(request N)` is added) |

### Timeouts

Any timeout stops the run; results so far are still reported.

| Option | Default | Meaning |
|---|---|---|
| `--request-timeout` | 20m | Longest one request may take |
| `--idle-timeout` | 15m | Longest a request may go without new output |
| `--stage-timeout` | 25m | Longest one round or stage may take |
| `--total-timeout` | off | Longest the whole run may take |
| `--settle-time` | 15s | Pause between stages |

### Output

| Option | Default | Meaning |
|---|---|---|
| `--output-dir` | `/tmp/load_test_<you>` | Where results go |
| `--no-dry-run` | off | Skip the probe and the cost question |
| `--no-tokens` | off | Don't count tokens |
| `--minimal` | off | Less traffic; client-side token counts are lost |
| `--archive-server-log` | off | Save a gzipped copy of the server log |
| `--history-file PATH` | `<output>/history.jsonl` | File used by `--trend` |
| `--compare DIR`, `--compare-agent` | | See [Comparing runs](#comparing-runs) |
| `--compare-baseline N`, `--compare-runs` | | See [Comparing runs](#comparing-runs) |
| `--trend PATH` | | See [Comparing runs](#comparing-runs) |
| `--rebuild DIR`, `--rebuild-all` | | Rebuild `raw_results.json` after a run was stopped (e.g. Ctrl+C) |

## Troubleshooting

- **Run stops right away about a mock LLM.** `OPENAI_API_BASE` is set, or
  `mock_llm_server` is running. Unset it / stop it. For a mock-LLM load
  test use `python tests/load_tests/load_test_mock_llm_service.py`.
- **`--level min` rejected.** Use `norm` or `adv`; `min` is only for
  `--client-only` / `--server-only`.
- **Asked about a missing server log.** Pass `--server-log PATH`, or
  `--no-server-log` to go on without it. For a remote server use
  `--client-only`.
- **No token numbers.** Don't use `--minimal`, or give the server log.
- **"WARNING: Server RSS ... risk of OOM kill".** The server is above 80%
  of the machine's memory; lower `--max-workers`.
- **Every request FAILED with an API key message.** The server is missing
  its LLM key; set it where the server runs.
