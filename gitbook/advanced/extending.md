# Extending the Framework

Neuro SAN is designed to be extensible. This guide covers common extension points.

## Adding a New LLM Provider

To add support for a new LLM provider:

### 1. Create an LLM Policy

Implement the `LlmPolicy` interface:

```python
class MyProviderLlmPolicy:

    def create_llm(self, config: dict) -> BaseLanguageModel:
        return MyProviderChatModel(
            model_name=config.get("model_name"),
            api_key=config.get("api_key"),
            **config
        )

    async def delete_resources(self):
        pass
```

### 2. Register in the LLM Factory

Add your provider to the factory's provider resolution logic so it recognizes model
name prefixes (e.g., `"myprovider/model-name"`).

### 3. Add Default Configuration

Create entries in `llm_info.hocon`:

```hocon
{
    "myprovider/model-v1": {
        "class": "MyProviderChatModel",
        "default_config": {
            "model_name": "model-v1",
            "temperature": 0.7
        }
    }
}
```

## Adding a New Tool Type

### CodedTool

The most common extension. Implement the `CodedTool` interface:

```python
from neuro_san.interfaces.coded_tool import CodedTool


class MyTool(CodedTool):

    def invoke(self, args: dict, sly_data: dict) -> dict:
        return {"response": "result"}
```

See [Writing CodedTools](../guides/coded-tools.md) for the full guide.

### Toolbox Tool

Add a new entry to `toolbox_info.hocon`:

```hocon
{
    "my_new_tool": {
        "class": "my_module.MyTool",
        "display_as": "coded_tool",
        "args": { ... }
    }
}
```

## Adding a New Client Protocol

To add a new client protocol:

1. Implement the `AgentSession` interface
2. Create a session factory
3. Add the connection mode to the CLI

The existing `DirectAgentSession`, `HttpServiceAgentSession`, and
`McpServiceAgentSession` serve as reference implementations.

## Adding a New Server Protocol

To expose agents through a new protocol:

1. Create a handler that receives requests and translates them to agent calls
2. Register the handler with the `ServerMainLoop`
3. Use `AgentNetworkStorage` to access available agents
4. Use `AsyncAgentService` to execute agent calls

The MCP handler (`McpRootHandler`) is a good reference implementation for adding
new protocols.

## Next Steps

- [Architecture Overview](architecture.md) -- Understand the system design
- [Contributing](contributing.md) -- Contribution workflow
