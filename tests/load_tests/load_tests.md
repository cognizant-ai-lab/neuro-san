# Load Test

Send many requests at once to a neuro-san server and see how it holds up:
how many requests succeed, how long they take, how many tokens they cost,
and how much memory the server uses.

The load test makes real LLM calls, so every run costs money.

## Before you start

Run everything below from the root of your neuro-san checkout. In each terminal you use, set up the environment:

```bash
export PYTHONPATH=$(pwd)
export AGENT_TOOL_PATH=./neuro_san/coded_tools
export AGENT_MANIFEST_FILE=./neuro_san/registries/manifest.hocon
```

## Quick start

Terminal 1: set your OpenAI key and start the server:

```bash
export OPENAI_API_KEY=<your key>
python -m neuro_san.service.main_loop.server_main_loop
```

Terminal 2: run the load test against the `hello_world` agent:

```bash
python -m tests.load_tests.load_test_cli --agent hello_world --client-only --fixtures-hocon-dir
```

`--fixtures-hocon-dir` with no folder looks for test cases in `tests/fixtures/load_tests/<agent>/`
at the top of your neuro-san checkout. Each test case is one hocon file with a prompt and the
checks on its answer. hello_world has five. To use test cases from another folder, see
[Prompts and checks](#prompts-and-checks).

By default it sends 3 requests, 3 at a time, so it runs three of the test cases.

It first sends one probe request, shows what the full run will cost, and asks
before sending the rest. A good run ends with `LOAD TEST PASSED`. Results are
saved under `/tmp/load_test_<you>/` (see [Results](#results)).

For every option, run:

```bash
python -m tests.load_tests.load_test_cli --help
```

## More load

These run the same five `hello_world` test cases. Requests take them in turn and start over
when all five are used, so 100 requests run each one 20 times. Every answer is checked against its test case.

```bash
# 100 requests, 10 at a time
python -m tests.load_tests.load_test_cli --agent hello_world --client-only --fixtures-hocon-dir \
    --num-requests 100 --max-workers 10

# Step up the load: 2, then 4, then 8 requests at once
python -m tests.load_tests.load_test_cli --agent hello_world --client-only --fixtures-hocon-dir \
    --ramp --stages 2,4,8

# Server on another machine
python -m tests.load_tests.load_test_cli --agent hello_world --client-only --fixtures-hocon-dir \
    --host my-server.example.com --https
```

Add `--no-dry-run` to skip the probe and the cost question, for example in scripts.

## Prompts and checks

The load test works with any agent the server serves. Pass `--agent <name>` and put its test cases
in `tests/fixtures/load_tests/<name>/`, one hocon file each.

To keep test cases somewhere else, give the parent folder: `--fixtures-hocon-dir /my/fixtures`
reads `/my/fixtures/<name>/*.hocon`.

For example, `tests/fixtures/load_tests/hello_world/greet_in_languages.hocon`:

```hocon
{
    "agent": "hello_world",
    "failure_patterns": [
        "No fully-specified LLM found",
        "API key to be set as an environment variable"
    ],
    "interactions": [
        {
            "text": "Can you greet me in different languages?"
        }
    ]
}
```

- `text`: the prompt.
- `response` (optional, next to `text`): what the answer must contain. See
  [test_case_hocon_reference.md](../../docs/test_case_hocon_reference.md) for all the checks.
- `failure_patterns` (optional): text that marks a request as failed even when the server answered.
- Put one interaction in each file.

Without `--fixtures-hocon-dir`, prompts come from
`tests/load_tests/prompts/profiles/<agent>.json` (being phased out).

## Watching the server too

When the server runs on the same machine, drop `--client-only`. The load test
then also tracks the server's memory and threads, and reads the server log
for retries and disconnections.

Terminal 1: start the server with its log in `/tmp`:

```bash
python -m neuro_san.service.main_loop.server_main_loop 2>&1 | tee /tmp/neuro_san_server.log
```

Terminal 2:

```bash
python -m tests.load_tests.load_test_cli --agent hello_world --fixtures-hocon-dir \
    --server-log /tmp/neuro_san_server.log
```

Both levels measure pass/fail per request, timings, tokens, cost, server memory and threads,
and, with the server log, retries and disconnections. Pick one with `--level`:

- `norm` (default): a short run. It sends one probe request first and asks before sending the rest.
- `adv`: a longer run, 50 requests x 3 rounds unless you set them. No probe, and it writes a `summary.txt` report.

Use `--no-server-log` to run without the server log.

To watch a server on another machine, run the same command on both machines:
`--server-only` on the server (watches it, sends nothing) and `--client-only`
on the client (sends the requests).

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

### What a run prints

At the end of a client-only run you see something like this (10 requests):

```text
============================================================
  OVERALL RESULTS
============================================================
  Total requests: 10
    Created:   10
    Failed:    0
    Timed out: 0
    Killed:    0
  Total wall time: 6.91s
  Time to first response: 2s min / 3s avg / 4s max
  Request duration: 3s min / 5s avg / 7s max

============================================================
  LLM & TOKEN USAGE
============================================================
  Client (HTTP token_accounting):
    LLM calls: 10 total  (1 / 1 / 1 min/avg/max)
    Tokens:    9,900 total  (900 / 990 / 1,080 min/avg/max),  7,000 prompt + 2,900 completion
  Server log: not available
  LLM models: gpt-4o (10)

============================================================
  LATENCY ANALYSIS
============================================================

  Completion percentiles (Round 1, 10 requests): p0 3.2s / p50 5.1s / p90 6.3s / p95 6.6s / p100 6.9s

LOAD TEST PASSED: all 10 requests completed successfully
```

- **Created**: requests that got a full answer. **Failed**, **Timed out** and **Killed** are the ones that did not.
- **Total wall time**: how long the whole run took.
- **Time to first response**: how long a request waited before the first part of the answer came back.
- **Request duration**: how long a request took from sending it to the full answer.
- **Tokens**: what the run used, which is what you pay for. "Server log" is only filled in when you also
  watch the server (see [Watching the server too](#watching-the-server-too)).
- **Completion percentiles**: `pN` is the time by which N% of the requests had finished.
  Above, `p50 5.1s` means half the requests finished within 5.1 seconds, and `p90 6.3s` means 9 out of 10
  finished within 6.3 seconds. `p0` is the fastest request and `p100` the slowest.
  If p100 is far above p90, a few requests were much slower than the rest.

With more than 50 requests it also lists how many requests had finished by when. With more than one round
at the same load, it shows whether the average time grew from round to round.

The command exits with `0` when every request succeeded and `1` otherwise.

## Comparing runs

```bash
# Side by side, sorted by request count: "how does it behave as load grows?"
python -m tests.load_tests.load_test_cli --compare /tmp/load_test_<you>/min/

# In time order: "did the same load get slower than before?"
python -m tests.load_tests.load_test_cli --trend /tmp/load_test_<you>/history.jsonl
```

`--client-only` runs are saved under `min/`, the others under `norm/` or `adv/`.
Neither command sends any requests.

## Troubleshooting

- **Run stops right away about a mock LLM.** `OPENAI_API_BASE` is set, or
  `mock_llm_server` is running. Unset it or stop it.
- **`--level min` rejected.** Use `norm` or `adv`. `min` is only for
  `--client-only` and `--server-only`.
- **Asked about a missing server log.** Pass `--server-log PATH`, or
  `--no-server-log` to go on without it.
- **"WARNING: Server RSS ... risk of OOM kill".** The server is using more than 80%
  of the machine's memory. Lower `--max-workers`.
- **Every request FAILED with an API key message.** Set `OPENAI_API_KEY` in the
  server's terminal and restart the server.
