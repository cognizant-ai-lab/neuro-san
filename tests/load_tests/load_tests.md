# Load Test

Send many requests at once to a neuro-san server and see how it holds up:
how many requests succeed, how long they take, and how many tokens they cost.

Use it to gather statistics on how requests are handled, so you can measure how your performance
optimization ideas fare. The requests come from neuro-san test case hocon files, so the test cases
you already have can be the basis for your load testing (see [Prompts and checks](#prompts-and-checks)).

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

## Results

Each run gets its own folder, `/tmp/load_test_<you>/<level>/<time>_<host>_<requests>/`
(or under `--output-dir`):

| File                  | What's in it                                  |
|-----------------------|-----------------------------------------------|
| `raw_results.json`    | Everything from the run                       |
| `summary.txt`         | Readable report (`--level adv` only)          |
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

`--client-only` runs are saved under `min/`. Runs that also watch the server (see
[Watching the server too](#watching-the-server-too)) are saved under `norm/` or `adv/`.
Neither command sends any requests.

## Watching the server too

This part is optional. Everything above works without it.

Client-only tells you what the client saw. When the server runs on the same machine, drop
`--client-only` and the load test also watches the server. That answers three more questions:
did the client and the server count the same tokens, did the server hold on to memory after the run,
and did the server log any errors.

Terminal 1: stop the Quick start server (Ctrl+C) and start it again with its log in `/tmp`:

```bash
export OPENAI_API_KEY=<your key>
python -m neuro_san.service.main_loop.server_main_loop 2>&1 | tee /tmp/neuro_san_server.log
```

Terminal 2: the same command as Quick start, without `--client-only`, and with `--server-log`
to say where that log is:

```bash
python -m tests.load_tests.load_test_cli --agent hello_world --fixtures-hocon-dir \
    --server-log /tmp/neuro_san_server.log
```

It runs the same `hello_world` test cases as Quick start. Like Quick start, it first sends one probe
request and asks before sending the rest.

### What you get on top of client-only

You get everything from [What a run prints](#what-a-run-prints), plus parts like these (10 requests, shortened):

```text
============================================================
  LLM & TOKEN USAGE
============================================================
  Client (HTTP token_accounting):
    LLM calls: 10 total  (1 / 1 / 1 min/avg/max)
    Tokens:    9,900 total  (900 / 990 / 1,080 min/avg/max),  7,000 prompt + 2,900 completion
  Server log:
    LLM calls: 10 total  (1 / 1 / 1 min/avg/max)
    Tokens:    9,900 total  (900 / 990 / 1,080 min/avg/max),  7,000 prompt + 2,900 completion
  Match: OK
  LLM models: gpt-4o (10)

============================================================
  RESOURCE ANALYSIS (10 client requests, 10 server calls)
============================================================
 Component  Concurrent  Before RSS  Peak RSS  Settled RSS  RSS Delta  CPU%  FDs   Threads  Thread Delta  Conns  Children
------------------------------------------------------------------------------------------------------------------------
Server app          10      412.3M        na       431.8M     +19.5M  3.1%   45  38 -> 42            +4      2         0
Client app          10      180.2M    205.6M       188.4M      +8.2M  0.4%   14         5            na     na        na
```

What to look at:

- **Do the token counts agree?** "Client" is what the client counted, "Server log" is what the server
  wrote down. `Match: OK` means they agree. `MISMATCH` means they don't, so look at the server log.
- **Did the server keep memory?** RSS is the memory a program uses. In the `Server app` row,
  **RSS Delta** is how much more memory the server uses after the run than before it.
  Run the same command a few times. If RSS Delta goes up again each time, the server keeps memory
  from requests that are done, and a server left running will slowly run out of memory.
  Look first at the coded tools your agent uses, since they run inside the server.
- **Did the server keep threads?** **Thread Delta** is how many more threads the server has after
  the run. If it goes up again each time you run the same command, something starts threads and never
  stops them. Again, look first at your agent's coded tools.
- The other columns (CPU%, open files, connections) are there to help when you dig into a problem.
- A **SYSTEM RESOURCES** part shows the whole machine's memory and CPU before, at the busiest point,
  and after the run. If the machine is nearly full at the busiest point, slow results may come from
  the machine, not the server.
- If the server log shows errors, or clients that gave up before the server finished, they are
  listed by request.

### Levels

The level sets how long the run is. Both levels watch the server as described above. Pick one with `--level`:

- `norm` (default): a short run. It sends one probe request first and asks before sending the rest.
- `adv`: a longer run, 50 requests x 3 rounds unless you set them. No probe, and it writes a `summary.txt` report.

### Server on another machine

When the server is on another machine, run the load test twice, once on each machine.
`--level` does not apply here.

1. On the server machine, start the server with its log in `/tmp` as above. Then, in a second terminal,
   start the watcher. It sends nothing; it watches the server and reads its log:

   ```bash
   python -m tests.load_tests.load_test_cli --agent hello_world --fixtures-hocon-dir \
       --server-only --server-log /tmp/neuro_san_server.log
   ```

   It asks how many requests the client will send. Type the same number you give the client.
   Press Ctrl+C at that question to stop.

2. On the client machine, send the requests as in [More load](#more-load), with `--host`
   set to the server machine.

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
