# FAQ & Troubleshooting

Common questions and solutions for Neuro SAN.

## General

### What is the difference between neuro-san and neuro-san-studio?

**neuro-san** is the core library that provides the multi-agent framework, server
infrastructure, and client interfaces. Install it via `pip install neuro-san`.

**neuro-san-studio** is a development environment built on top of the library. It adds
a web UI, dozens of example agent networks, a toolbox catalog, and the Agent Network
Designer. Clone it from GitHub to get started quickly.

### Do I need to write Python code to use Neuro SAN?

No. Agent networks are defined entirely in HOCON configuration files. You only need
Python code if you want to create custom CodedTools that interact with external APIs
or databases. Many useful networks can be built with just HOCON and the built-in
toolbox tools.

### Which LLM provider should I use?

For getting started, **OpenAI GPT-4o** is the default and most widely tested. For
production, choose based on your requirements:

- **Best general performance:** OpenAI GPT-4o
- **Best for long context:** Anthropic Claude 3.5 Sonnet
- **Best for cost:** OpenAI GPT-4o-mini or local Ollama models
- **Best for privacy:** Ollama (runs locally, no data leaves your machine)
- **Enterprise compliance:** Azure OpenAI or Amazon Bedrock

### Can I use multiple LLM providers in the same network?

Yes. Set a default at the network level and override per-agent. For example, use
`gpt-4o-mini` for simple routing agents and `gpt-4o` for complex reasoning agents.

## Installation

### `ModuleNotFoundError: No module named 'neuro_san'`

Make sure `PYTHONPATH` is set to the project root:

```bash
export PYTHONPATH=$(pwd)
```

### `ImportError: cannot import name 'CodedTool'`

Ensure neuro-san is installed:

```bash
pip install neuro-san
```

Or if running from source, check that `requirements.txt` dependencies are installed.

## API Keys

### `AuthenticationError: Invalid API key`

- Verify the environment variable is set: `echo $OPENAI_API_KEY`
- Check for trailing spaces or newlines in the key
- Confirm the key is active in your provider's dashboard
- Make sure you set the correct variable for your provider

### `RateLimitError: Rate limit exceeded`

- Configure fallback models in `llm_config`:
  ```hocon
  "fallbacks": [{"model_name": "claude-3-5-sonnet-20241022"}]
  ```
- Reduce concurrent requests
- Use a model with higher rate limits

## Agent Networks

### Agent stops with "max iterations reached"

The agent is calling tools in a loop without converging on an answer. Common causes:

- **Circular delegation:** Agent A calls Agent B, which calls Agent A
- **Unclear instructions:** The agent doesn't know when to stop delegating
- **Missing information:** The agent keeps asking tools for data that isn't available

**Fix:** Review agent instructions. Make them specific about when to stop delegating
and when to respond directly. Check for circular tool references.

### Wrong agent handles the request

The Front Man is delegating to the wrong sub-agent. This usually means:

- **Function descriptions are too vague:** Make each agent's `function.description`
  clearly state what it handles
- **Instructions are ambiguous:** Add explicit routing rules to the Front Man's
  instructions
- **Missing AAOSA:** If agents have overlapping domains, use the AAOSA protocol

### Agent returns empty or generic responses

- Check that the agent's `instructions` are clear and specific
- Verify the LLM model supports tool calling (not all models do)
- Check logs for errors: `AGENT_LOG_LEVEL=DEBUG`
- Try a more capable model (e.g., switch from `gpt-4o-mini` to `gpt-4o`)

## CodedTools

### `Tool not found: coded_tools.my_tool.MyTool`

- Verify `AGENT_TOOL_PATH` is set correctly: `echo $AGENT_TOOL_PATH`
- Check that the Python file exists at the specified path
- Verify the class name matches exactly (case-sensitive)
- Make sure the directory has an `__init__.py` file

### CodedTool not receiving sly\_data

- Verify the upstream agent has `allow.to_downstream.sly_data` configured
- Check that the client is sending sly\_data with the request
- sly\_data keys are case-sensitive

## Server

### `Address already in use` (port conflict)

Another process is using the port. Either:

- Stop the other process: `lsof -i :8080` to find it
- Use a different port: `--http-port 8081`

### Server doesn't detect HOCON changes

- Check that hot reload is enabled: `--manifest-update-period-seconds 60`
- Verify the file was saved (not just modified in an editor buffer)
- Check server logs for reload events

### MCP endpoint returns 404

- Verify the agent has `mcp: true` in the manifest
- Check that the server is running and the HTTP port is accessible
- Confirm you're using the correct endpoint: `/mcp`

## Docker

### Container exits immediately

Check the logs: `docker logs <container_id>`

Common causes:

- Missing environment variables (especially API keys)
- Port conflicts with the host
- Insufficient memory

### Can't access server from host

Make sure ports are published:

```bash
docker run --publish 8080:8080 --publish 30011:30011 neuro-san
```

And that the server binds to `0.0.0.0`:

```bash
export NEURO_SAN_SERVER_HOST="0.0.0.0"
```
