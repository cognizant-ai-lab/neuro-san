# Configuring LLMs

This guide covers how to configure LLM providers, set up fallbacks, use reasoning models,
and optimize model selection for your agent networks.

## Setting the Default LLM

Every agent network needs an `llm_config` at the top level. This sets the default model
for all agents in the network:

```hocon
{
    "llm_config": {
        "model_name": "gpt-4o"
    }
}
```

### Common Parameters

| Parameter | Description | Default |
|:----------|:------------|:--------|
| `model_name` | The model identifier | Required |
| `temperature` | Randomness (0.0 = deterministic, 1.0 = creative) | Provider default |
| `max_tokens` | Maximum response length | Provider default |

```hocon
"llm_config": {
    "model_name": "gpt-4o",
    "temperature": 0.3,
    "max_tokens": 4096
}
```

## Switching Providers

Change the `model_name` to use a different provider. Make sure the corresponding API key
environment variable is set.

### OpenAI

```bash
export OPENAI_API_KEY="sk-..."
```

```hocon
"llm_config": {
    "model_name": "gpt-4o"
}
```

### Anthropic

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

```hocon
"llm_config": {
    "model_name": "claude-3-5-sonnet-20241022"
}
```

### Google Gemini

```bash
export GOOGLE_API_KEY="..."
```

```hocon
"llm_config": {
    "model_name": "gemini-2.0-flash"
}
```

### Azure OpenAI

```bash
export AZURE_OPENAI_API_KEY="..."
export AZURE_OPENAI_ENDPOINT="https://your-resource.openai.azure.com/"
```

```hocon
"llm_config": {
    "model_name": "azure/gpt-4o",
    "api_version": "2024-02-15-preview",
    "azure_endpoint": "https://your-resource.openai.azure.com/"
}
```

### Amazon Bedrock

```bash
export AWS_ACCESS_KEY_ID="..."
export AWS_SECRET_ACCESS_KEY="..."
```

```hocon
"llm_config": {
    "model_name": "bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0",
    "region_name": "us-east-1"
}
```

### Ollama (Local)

No API key needed. Install and start Ollama first:

```bash
ollama pull llama3
ollama serve
```

```hocon
"llm_config": {
    "model_name": "ollama/llama3",
    "base_url": "http://localhost:11434"
}
```

## Per-Agent Overrides

Override the LLM for specific agents by adding `llm_config` to the agent definition:

```hocon
{
    "llm_config": {
        "model_name": "gpt-4o-mini"
    },
    "tools": [
        {
            "name": "router",
            "instructions": "Route requests to the right agent."
        },
        {
            "name": "analyst",
            "llm_config": {
                "model_name": "gpt-4o"
            },
            "instructions": "Perform detailed analysis."
        },
        {
            "name": "summarizer",
            "llm_config": {
                "model_name": "claude-3-5-sonnet-20241022"
            },
            "instructions": "Create concise summaries."
        }
    ]
}
```

In this example:
- **router** uses `gpt-4o-mini` (the default) since routing is simple
- **analyst** uses `gpt-4o` for more complex reasoning
- **summarizer** uses Claude, which may produce different summary styles

## Configuring Fallbacks

Fallbacks provide resilience when a model is unavailable:

```hocon
"llm_config": {
    "model_name": "gpt-4o",
    "fallbacks": [
        {
            "model_name": "claude-3-5-sonnet-20241022"
        },
        {
            "model_name": "gemini-2.0-flash"
        }
    ]
}
```

If `gpt-4o` fails (rate limit, outage, error), the system automatically tries the next
model in the fallback list.

## Reasoning Models

Reasoning models (like OpenAI `o1`, `o3-mini`) perform extended internal reasoning:

```hocon
"llm_config": {
    "model_name": "o1",
    "reasoning": true
}
```

Setting `reasoning: true` tells the framework to:
- Skip the system prompt (reasoning models don't use them the same way)
- Omit temperature settings (reasoning models manage this internally)
- Adjust tool-calling behavior for compatibility

Use reasoning models for agents that need deep analytical thinking, such as math,
logic puzzles, or complex planning.

## Custom LLM Definitions

For models not in the default catalog, define them in an `llm_info.hocon` file:

```hocon
{
    "my-custom-model": {
        "class": "ChatOpenAI",
        "default_config": {
            "model_name": "my-custom-model",
            "openai_api_base": "https://my-endpoint.com/v1",
            "temperature": 0.7
        }
    }
}
```

Set the environment variable to point to your file:

```bash
export AGENT_LLM_INFO_FILE="path/to/llm_info.hocon"
```

See [LLM Info Reference](../reference/llm-info.md) for the complete specification.

## Cost Optimization Tips

1. **Use cheaper models for simple tasks.** Routing agents, formatters, and simple
   lookup agents can use `gpt-4o-mini` or similar lightweight models.
2. **Reserve powerful models for complex reasoning.** Only the agents that need deep
   analysis should use `gpt-4o` or `o1`.
3. **Set max\_tokens appropriately.** Don't allocate 4096 tokens for agents that produce
   short responses.
4. **Use local models for development.** Ollama with `llama3` is free and fast for testing
   network structure before switching to cloud models.

## Next Steps

- [LLM Info Reference](../reference/llm-info.md) -- Complete LLM configuration reference
- [Writing CodedTools](coded-tools.md) -- Add capabilities to your agents
