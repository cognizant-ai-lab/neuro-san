# Environment Variables

Complete reference of all environment variables used by Neuro SAN.

## API Keys

| Variable | Provider | Required |
|:---------|:---------|:---------|
| `OPENAI_API_KEY` | OpenAI | For OpenAI models |
| `ANTHROPIC_API_KEY` | Anthropic | For Claude models |
| `GOOGLE_API_KEY` | Google | For Gemini models |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI | For Azure-hosted models |
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI | Azure resource endpoint |
| `AWS_ACCESS_KEY_ID` | Amazon Bedrock | For Bedrock models |
| `AWS_SECRET_ACCESS_KEY` | Amazon Bedrock | For Bedrock models |

## Agent Configuration

| Variable | Default | Description |
|:---------|:--------|:------------|
| `AGENT_MANIFEST_FILE` | `registries/manifest.hocon` | Path to manifest file(s), space-separated for overlays |
| `AGENT_TOOL_PATH` | `coded_tools` | Directory containing CodedTool Python files |
| `AGENT_TOOLBOX_INFO_FILE` | *(built-in)* | Path to toolbox HOCON file |
| `AGENT_LLM_INFO_FILE` | *(built-in)* | Path to custom LLM info HOCON file |
| `AGENT_MCP_INFO_FILE` | *(none)* | Path to shared MCP server configuration |

## Server Configuration

| Variable | Default | Description |
|:---------|:--------|:------------|
| `NEURO_SAN_SERVER_HOST` | `localhost` | Server bind address |
| `NEURO_SAN_SERVER_GRPC_PORT` | `30011` | gRPC server port |
| `NEURO_SAN_SERVER_HTTP_PORT` | `8080` | HTTP server port |
| `AGENT_MANIFEST_UPDATE_PERIOD_SECONDS` | `60` | Manifest hot-reload interval (0 = disabled) |
| `AGENT_TEMPORARY_NETWORK_UPDATE_PERIOD_SECONDS` | `0` | Temporary network processing interval |
| `AGENT_MAX_CONCURRENT_REQUESTS` | *(system default)* | Maximum concurrent request processing |

## Logging

| Variable | Default | Description |
|:---------|:--------|:------------|
| `AGENT_LOG_LEVEL` | `INFO` | Log level (DEBUG, INFO, WARNING, ERROR) |
| `AGENT_SERVICE_LOG_JSON` | *(none)* | Path to JSON logging configuration file |

## Observability

| Variable | Default | Description |
|:---------|:--------|:------------|
| `PHOENIX_ENABLED` | `false` | Enable Phoenix LLM tracing |

## Search Tools

| Variable | Provider | Description |
|:---------|:---------|:------------|
| `TAVILY_API_KEY` | Tavily | Web search API key |
| `BRAVE_API_KEY` | Brave | Brave search API key |
| `SERPER_API_KEY` | Serper | Google Serper API key |
| `GOOGLE_CSE_ID` | Google CSE | Custom Search Engine ID |

## Other Integrations

| Variable | Description |
|:---------|:------------|
| `JIRA_API_TOKEN` | Jira integration token |
| `JIRA_USERNAME` | Jira username |
| `JIRA_INSTANCE_URL` | Jira instance URL |
| `GMAIL_CREDENTIALS_FILE` | Path to Gmail OAuth credentials |

## Setting Environment Variables

### Directly in the Shell

```bash
export OPENAI_API_KEY="sk-..."
export AGENT_LOG_LEVEL="DEBUG"
```

### Using a .env File (Studio)

Create a `.env` file in the project root:

```bash
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
AGENT_LOG_LEVEL=DEBUG
PHOENIX_ENABLED=true
```

Neuro SAN Studio automatically loads `.env` files at startup.

### In Docker

Pass environment variables via `docker run`:

```bash
docker run -e OPENAI_API_KEY="sk-..." -e AGENT_LOG_LEVEL="DEBUG" neuro-san
```

Or use an env file:

```bash
docker run --env-file .env neuro-san
```
