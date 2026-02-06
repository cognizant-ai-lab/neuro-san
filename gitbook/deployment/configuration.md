# Production Configuration

This guide covers configuring Neuro SAN for production deployments.

## Environment Setup

### Required Variables

At minimum, set your LLM provider key and server configuration:

```bash
export OPENAI_API_KEY="sk-..."
export NEURO_SAN_SERVER_HOST="0.0.0.0"
export NEURO_SAN_SERVER_HTTP_PORT="8080"
export NEURO_SAN_SERVER_GRPC_PORT="30011"
```

### Using .env Files

For Neuro SAN Studio, create a `.env` file from the template:

```bash
cp .env.example .env
```

The `.env` file is loaded automatically at startup. See
[Environment Variables](../reference/environment-variables.md) for the complete list.

## Server Configuration

### Hot Reload

Enable automatic reloading when HOCON files change:

```bash
python -m neuro_san.service.main_loop.server_main_loop \
    --manifest-update-period-seconds 60
```

Set to `0` to disable in production for stability.

### Concurrent Requests

Control the maximum number of simultaneous requests:

```bash
export AGENT_MAX_CONCURRENT_REQUESTS=10
```

### Temporary Networks

Enable temporary network support (required for Agent Network Designer and Copy Cat):

```bash
export AGENT_TEMPORARY_NETWORK_UPDATE_PERIOD_SECONDS=300
```

Set to `0` to disable.

## Agent Registry

### Manifest Configuration

Point to your production manifest:

```bash
export AGENT_MANIFEST_FILE="registries/manifest.hocon"
```

### Custom Tool Paths

Set the path to your CodedTool implementations:

```bash
export AGENT_TOOL_PATH="./coded_tools"
```

### Custom Toolbox

Use a project-specific toolbox:

```bash
export AGENT_TOOLBOX_INFO_FILE="./toolbox/toolbox_info.hocon"
```

## Logging Configuration

### JSON Logging

For structured log output suitable for log aggregation:

```bash
export AGENT_SERVICE_LOG_JSON="deploy/logging.json"
```

### Log Level

Set the appropriate level for production:

```bash
export AGENT_LOG_LEVEL="INFO"
```

Use `DEBUG` only for troubleshooting -- it produces significant output.

## Next Steps

- [Security](security.md) -- Multi-user access control
- [Observability](observability.md) -- Monitoring and tracing
- [Environment Variables](../reference/environment-variables.md) -- Complete reference
