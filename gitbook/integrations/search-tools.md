# Search Tools

Neuro SAN supports multiple web search providers through the toolbox. This guide compares
available options to help you choose the right one for your use case.

## Available Search Tools

| Tool | Provider | Free Tier | API Key Required |
|:-----|:---------|:----------|:-----------------|
| `ddgs_search` | DuckDuckGo | Unlimited | No |
| `brave_search` | Brave | 2,000/month | Yes |
| `tavily_search` | Tavily | 1,000/month | Yes |
| `google_serper` | Serper | 2,500/month | Yes |
| `google_search` | Google CSE | 100/day | Yes |
| `openai_search` | OpenAI | Per-token pricing | Yes |
| `anthropic_search` | Anthropic | Per-token pricing | Yes |

## Setup

### DuckDuckGo (No API Key)

The simplest option. No configuration needed:

```hocon
"tools": [{"toolbox_tool": "ddgs_search"}]
```

### Brave Search

```bash
export BRAVE_API_KEY="your-key"
```

```hocon
"tools": [{"toolbox_tool": "brave_search"}]
```

### Tavily Search

```bash
export TAVILY_API_KEY="your-key"
```

```hocon
"tools": [{"toolbox_tool": "tavily_search"}]
```

### Google Serper

```bash
export SERPER_API_KEY="your-key"
```

```hocon
"tools": [{"toolbox_tool": "google_serper"}]
```

### Google Custom Search

```bash
export GOOGLE_API_KEY="your-key"
export GOOGLE_CSE_ID="your-cse-id"
```

```hocon
"tools": [{"toolbox_tool": "google_search"}]
```

### OpenAI Web Search

```bash
export OPENAI_API_KEY="your-key"
```

```hocon
"tools": [{"toolbox_tool": "openai_search"}]
```

### Anthropic Web Search

```bash
export ANTHROPIC_API_KEY="your-key"
```

```hocon
"tools": [{"toolbox_tool": "anthropic_search"}]
```

## Comparison

| Feature | DuckDuckGo | Brave | Tavily | Google Serper | OpenAI | Anthropic |
|:--------|:-----------|:------|:-------|:-------------|:-------|:----------|
| Cost | Free | Freemium | Freemium | Freemium | Per-token | Per-token |
| Quality | Good | Very Good | Excellent | Excellent | Excellent | Excellent |
| Speed | Fast | Fast | Fast | Fast | Moderate | Moderate |
| Rate Limits | Unofficial | 2K/month free | 1K/month free | 2.5K/month free | Token-based | Token-based |
| Best For | Development | Production | AI-optimized | Google results | Integrated search | Integrated search |

## Recommendations

- **Development/testing** -- Use `ddgs_search` (free, no setup)
- **Production (budget-conscious)** -- Use `brave_search` or `google_serper`
- **Production (quality-focused)** -- Use `tavily_search` (optimized for AI agents)
- **Already using OpenAI/Anthropic** -- Use their built-in search tools

## Next Steps

- [Using the Toolbox](../guides/using-toolbox.md) -- How to use toolbox tools
- [Toolbox Reference](../reference/toolbox.md) -- Complete tool catalog
