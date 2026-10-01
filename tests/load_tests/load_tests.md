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

At the end of each run you also get:

- **Completion timeline**: how many requests had come back by when.
- **Round-over-round latency**: whether the same load got slower each round.
- **Concurrency chart**: how many requests were really in flight over time.

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
