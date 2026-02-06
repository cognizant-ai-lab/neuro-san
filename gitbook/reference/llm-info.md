# LLM Info HOCON Reference

The LLM Info file defines available LLM models and their configurations. It maps model
names to their provider class and default parameters.

## File Location

Neuro SAN ships with a built-in `default_llm_info.hocon` that covers common models.
To add custom models, create your own file and set:

```bash
export AGENT_LLM_INFO_FILE="path/to/llm_info.hocon"
```

Your file is merged with (overlays on top of) the default configuration.

## Format

Each entry maps a model name to its configuration:

```hocon
{
    "model-name": {
        "class": "LangChainClassName",
        "default_config": {
            "model_name": "model-name",
            "temperature": 0.7,
            ...provider-specific-params
        }
    }
}
```

## Fields

### Top-Level Key

The model name used in `llm_config.model_name` throughout agent HOCON files.

### class

The LangChain chat model class to instantiate. Common values:

| Class | Provider |
|:------|:---------|
| `ChatOpenAI` | OpenAI, Azure OpenAI, OpenAI-compatible APIs |
| `ChatAnthropic` | Anthropic |
| `ChatGoogleGenerativeAI` | Google Gemini |
| `ChatBedrock` | Amazon Bedrock |
| `ChatOllama` | Ollama (local) |

### default\_config

Default parameters passed to the LangChain class constructor. Common fields:

| Field | Type | Description |
|:------|:-----|:------------|
| `model_name` | string | Model identifier for the provider |
| `temperature` | float | Default sampling temperature |
| `max_tokens` | integer | Default max response tokens |
| `openai_api_base` | string | Custom API endpoint (OpenAI-compatible) |
| `api_version` | string | API version (Azure) |
| `region_name` | string | AWS region (Bedrock) |
| `base_url` | string | Server URL (Ollama) |

## Examples

### Custom OpenAI-Compatible Model

```hocon
{
    "my-local-model": {
        "class": "ChatOpenAI",
        "default_config": {
            "model_name": "my-local-model",
            "openai_api_base": "http://localhost:8000/v1",
            "temperature": 0.7,
            "max_tokens": 2048
        }
    }
}
```

### Azure OpenAI Deployment

```hocon
{
    "azure/my-gpt4": {
        "class": "ChatOpenAI",
        "default_config": {
            "model_name": "my-gpt4-deployment",
            "openai_api_base": "https://my-resource.openai.azure.com/",
            "api_version": "2024-02-15-preview"
        }
    }
}
```

### Bedrock Model

```hocon
{
    "bedrock/anthropic.claude-3-5-sonnet": {
        "class": "ChatBedrock",
        "default_config": {
            "model_id": "anthropic.claude-3-5-sonnet-20241022-v2:0",
            "region_name": "us-east-1"
        }
    }
}
```

## Environment Variable Extensions

Model configurations can reference environment variables:

```hocon
{
    "my-model": {
        "class": "ChatOpenAI",
        "default_config": {
            "model_name": "my-model",
            "openai_api_base": ${MY_MODEL_ENDPOINT}
        }
    }
}
```

This is the recommended approach for API endpoints and other deployment-specific values.
