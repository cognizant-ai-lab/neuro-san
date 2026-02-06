# Logging and Debugging

Neuro SAN provides detailed logging to help you understand agent behavior, diagnose issues,
and optimize your networks.

## Log Levels

Neuro SAN uses Python's standard `logging` module with these levels:

| Level | Use |
|:------|:----|
| `DEBUG` | Detailed agent reasoning, tool calls, LLM interactions |
| `INFO` | Agent lifecycle events, request handling |
| `WARNING` | Non-fatal issues (fallback models, retries) |
| `ERROR` | Failures (API errors, tool exceptions) |

## Configuring Log Level

### Via Environment Variable

```bash
export AGENT_LOG_LEVEL="DEBUG"
```

### Via Command Line (Server)

```bash
python -m neuro_san.service.main_loop.server_main_loop --log-level DEBUG
```

## Log Output

### Standard Logging

By default, logs go to stderr. You'll see entries like:

```
INFO:neuro_san:Loading agent network: weather_assistant
DEBUG:neuro_san:FrontMan invoking tool: weather_lookup
DEBUG:neuro_san:Tool weather_lookup returned: Weather in NYC: Sunny, 72°F
INFO:neuro_san:Request completed in 2.3s
```

### JSON Logging

For production or structured log analysis, use JSON logging:

```bash
export AGENT_SERVICE_LOG_JSON="deploy/logging.json"
```

This outputs structured JSON logs suitable for log aggregation services.

### Thinking Logs (Studio)

In Neuro SAN Studio, per-agent reasoning logs are written to `logs/thinking_dir/`.
These capture each agent's thought process, tool calls, and decisions:

```
logs/
├── server.log
├── nsflow.log
└── thinking_dir/
    ├── weather_assistant/
    │   ├── front_man.log
    │   └── weather_lookup.log
```

## Observability with Phoenix

Neuro SAN Studio integrates with [Phoenix](https://phoenix.arize.com/) for tracing
LLM interactions:

```bash
export PHOENIX_ENABLED=true
```

Access the Phoenix UI at [http://localhost:6006/](http://localhost:6006/) to see:

- Individual LLM calls with prompts and responses
- Token usage per agent
- Latency breakdowns
- Tool call sequences

## Debugging Tips

### 1. Use Direct Mode

Run agents directly (without the server) for simpler debugging:

```bash
python -m neuro_san.client.agent_cli --agent my_agent
```

### 2. Validate HOCON First

Use the HOCON validator to catch configuration errors before running:

```bash
python -m neuro_san.client.hocon_validator_cli --verbose
```

### 3. Check Agent Delegation

Enable DEBUG logging to see which agents are called and what they return:

```bash
AGENT_LOG_LEVEL=DEBUG python -m neuro_san.client.agent_cli --agent my_agent
```

### 4. Test Individual Agents

Temporarily promote a sub-agent to Front Man to test it in isolation. Move it to the
first position in the `tools` list and run the network.

### 5. Common Issues

| Symptom | Likely Cause |
|:--------|:-------------|
| Agent loops / max iterations | Circular delegation or unclear instructions |
| Wrong agent handles request | Poor function descriptions or missing AAOSA pattern |
| Tool not found | Incorrect `coded_tool` path or missing `AGENT_TOOL_PATH` |
| API key errors | Missing or invalid environment variable |
| Slow responses | Too many agents, large context, or slow model |

## Next Steps

- [Testing](../testing/README.md) -- Automated testing for agent networks
- [HOCON Validator](../reference/hocon-validator.md) -- Configuration validation tool
- [FAQ](../faq.md) -- Common questions and solutions
