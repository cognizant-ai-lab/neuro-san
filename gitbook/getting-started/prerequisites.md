# Prerequisites

Before installing Neuro SAN, make sure you have the following:

## Python

Neuro SAN requires **Python 3.12 or 3.13**.

Check your version:

```bash
python --version
```

## API Keys

Neuro SAN works with multiple LLM providers. You need at least one API key to get started.
The default configuration uses **OpenAI GPT-4o**, so an OpenAI key is the simplest way to begin.

| Provider | Environment Variable | Where to Get a Key |
|:---------|:---------------------|:-------------------|
| OpenAI | `OPENAI_API_KEY` | [platform.openai.com](https://platform.openai.com/signup) |
| Anthropic | `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com/settings/keys) |
| Google Gemini | `GOOGLE_API_KEY` | [Google AI Studio](https://aistudio.google.com/) |
| Azure OpenAI | `AZURE_OPENAI_API_KEY` | [Azure Portal](https://portal.azure.com/) |
| Amazon Bedrock | `AWS_ACCESS_KEY_ID` | [AWS Console](https://console.aws.amazon.com/) |
| Ollama | *(none required)* | [ollama.com](https://ollama.com/) |

Set your key as an environment variable:

```bash
export OPENAI_API_KEY="your-api-key-here"
```

> **Security note:** Never put API keys directly in configuration files or source code.
> Always use environment variables.

## Optional

- **Docker** -- Required only if you plan to deploy as a container
- **Git** -- Required only if cloning from source
