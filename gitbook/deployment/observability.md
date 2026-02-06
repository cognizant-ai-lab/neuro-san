# Observability

Neuro SAN integrates with observability tools for monitoring LLM interactions, tracking
performance, and debugging production issues.

## Phoenix Integration

[Phoenix](https://phoenix.arize.com/) provides tracing and monitoring for LLM applications.

### Enabling Phoenix

```bash
export PHOENIX_ENABLED=true
```

When running Neuro SAN Studio, Phoenix starts automatically and is available at
[http://localhost:6006/](http://localhost:6006/).

### What Phoenix Shows

- **LLM call traces** -- Full prompt and response for each LLM interaction
- **Token usage** -- Input and output tokens per call
- **Latency** -- Time spent in each LLM call and tool execution
- **Tool call chains** -- Visualization of agent delegation sequences
- **Error tracking** -- Failed LLM calls and tool exceptions

## Structured Logging

### JSON Log Format

Enable structured JSON logging for production log aggregation:

```bash
export AGENT_SERVICE_LOG_JSON="deploy/logging.json"
```

JSON logs include:

- Timestamp
- Log level
- Logger name (includes agent origin path)
- Message
- Exception details (if any)

### Log Levels

| Level | When to Use |
|:------|:------------|
| `ERROR` | Production -- only failures |
| `WARNING` | Production -- failures and potential issues |
| `INFO` | Production -- standard operation events |
| `DEBUG` | Development -- full agent reasoning traces |

### Agent-Level Logging

Each agent in the network generates logs with its origin path, making it easy to trace
which agent produced each log entry:

```
INFO:neuro_san.customer_service.billing_agent:Processing refund request
DEBUG:neuro_san.customer_service.billing_agent.refund_processor:Calculating refund amount
```

## Thinking Logs (Studio)

Neuro SAN Studio writes per-agent reasoning logs to `logs/thinking_dir/`:

```
logs/thinking_dir/
├── customer_service/
│   ├── front_man.log
│   ├── billing_agent.log
│   └── support_agent.log
```

These capture the full chain of thought for each agent, including:

- System prompt
- User message
- Tool call decisions
- Tool responses
- Final output

## Other Observability Integrations

Neuro SAN Studio also supports:

- **LangSmith** -- LangChain's observability platform
- **HoneyHive** -- AI observability and evaluation

Consult the respective documentation for setup instructions.

## Next Steps

- [Logging and Debugging](../guides/logging.md) -- Development debugging guide
- [Testing](../testing/README.md) -- Automated testing infrastructure
