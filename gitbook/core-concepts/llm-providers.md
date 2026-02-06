# LLM Providers

Neuro SAN supports multiple LLM providers through a unified abstraction layer. You can
switch between providers by changing a single configuration value, and even mix providers
within the same agent network.

## Supported Providers

| Provider | Model Name Prefix | Environment Variable |
|:---------|:------------------|:--------------------|
| OpenAI | `gpt-4o`, `o1`, etc. | `OPENAI_API_KEY` |
| Anthropic | `claude-3-5-sonnet-*`, etc. | `ANTHROPIC_API_KEY` |
| Google Gemini | `gemini-*` | `GOOGLE_API_KEY` |
| Azure OpenAI | `azure/gpt-4o`, etc. | `AZURE_OPENAI_API_KEY` |
| Amazon Bedrock | `bedrock/anthropic.*`, etc. | `AWS_ACCESS_KEY_ID` |
| Ollama (local) | `ollama/llama3`, etc. | *(none)* |

## Basic Configuration

Set the LLM at the top level of your agent network HOCON file. This applies to all agents
unless overridden:

```hocon
{
    "llm_config": {
        "model_name": "gpt-4o"
    }
}
```

## Provider-Specific Examples

### OpenAI

```hocon
"llm_config": {
    "model_name": "gpt-4o",
    "temperature": 0.7,
    "max_tokens": 4096
}
```

### Anthropic

```hocon
"llm_config": {
    "model_name": "claude-3-5-sonnet-20241022",
    "temperature": 0.7
}
```

### Google Gemini

```hocon
"llm_config": {
    "model_name": "gemini-2.0-flash"
}
```

### Azure OpenAI

```hocon
"llm_config": {
    "model_name": "azure/gpt-4o",
    "api_version": "2024-02-15-preview",
    "azure_endpoint": "https://your-resource.openai.azure.com/"
}
```

### Amazon Bedrock

```hocon
"llm_config": {
    "model_name": "bedrock/anthropic.claude-3-5-sonnet-20241022-v2:0",
    "region_name": "us-east-1"
}
```

### Ollama (Local Models)

Run models locally without an API key:

```hocon
"llm_config": {
    "model_name": "ollama/llama3",
    "base_url": "http://localhost:11434"
}
```

## Per-Agent LLM Configuration

You can override the LLM for individual agents. This is useful when certain agents need
a more capable model while others can use a cheaper, faster one:

```hocon
{
    "llm_config": {
        "model_name": "gpt-4o-mini"
    },
    "tools": [
        {
            "name": "front_man",
            "instructions": "Route requests to the appropriate agent."
        },
        {
            "name": "complex_reasoner",
            "llm_config": {
                "model_name": "o1"
            },
            "instructions": "Solve complex analytical problems."
        }
    ]
}
```

In this example, most agents use `gpt-4o-mini` (fast and cheap), but the complex\_reasoner
uses `o1` (slower but more capable) for tasks that require deep reasoning.

## LLM Fallbacks

You can configure fallback models that are used if the primary model fails:

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

If `gpt-4o` fails (rate limit, outage, etc.), Neuro SAN automatically tries
`claude-3-5-sonnet`, then `gemini-2.0-flash`.

## Reasoning Models

Some models (like OpenAI's `o1` or `o3-mini`) are **reasoning models** that perform
extended internal reasoning before responding. These require special configuration:

```hocon
"llm_config": {
    "model_name": "o1",
    "reasoning": true
}
```

When `reasoning` is set to `true`, the framework adjusts how it interacts with the model
to account for the different behavior of reasoning models (e.g., no system prompt, no
temperature parameter).

## Custom LLM Configuration

For non-standard or custom models, you can define the full configuration in the
`llm_info.hocon` file:

```hocon
{
    "my-custom-model": {
        "class": "ChatOpenAI",
        "default_config": {
            "model_name": "my-custom-model",
            "openai_api_base": "https://my-custom-endpoint.com/v1",
            "temperature": 0.7
        }
    }
}
```

See [LLM Info Reference](../reference/llm-info.md) for the complete specification.

## Next Steps

- [LLM Info Reference](../reference/llm-info.md) -- Complete LLM configuration reference
- [Tools and CodedTools](tools.md) -- Add capabilities to your agents
