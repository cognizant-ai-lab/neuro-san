# Using the Toolbox

The Toolbox is a catalog of pre-configured tools that agents can use without writing
any Python code. Tools are defined in a `toolbox_info.hocon` file and referenced by
name in agent configurations.

## How It Works

1. A tool is defined in `toolbox_info.hocon` with its class, arguments, and schema
2. An agent references the tool by name in its `tools` list
3. At runtime, the framework instantiates the tool and makes it available to the agent

## Using a Toolbox Tool

Reference a toolbox tool in your agent's HOCON configuration:

```hocon
{
    "llm_config": {
        "model_name": "gpt-4o"
    },
    "tools": [
        {
            "name": "researcher",
            "function": {
                "description": "I research topics using web search."
            },
            "instructions": "You are a research assistant.
                Use the tavily_search tool to find information online.
                Summarize your findings clearly.",
            "tools": [
                {
                    "toolbox_tool": "tavily_search"
                }
            ]
        }
    ]
}
```

The `toolbox_tool` key tells the framework to look up the tool definition from the
toolbox catalog.

## Available Tool Categories

### Web Search

| Tool | Provider | Requires |
|:-----|:---------|:---------|
| `tavily_search` | Tavily | `TAVILY_API_KEY` |
| `brave_search` | Brave | `BRAVE_API_KEY` |
| `ddgs_search` | DuckDuckGo | *(none)* |
| `google_search` | Google CSE | `GOOGLE_CSE_ID`, `GOOGLE_API_KEY` |
| `google_serper` | Serper | `SERPER_API_KEY` |
| `openai_search` | OpenAI | `OPENAI_API_KEY` |
| `anthropic_search` | Anthropic | `ANTHROPIC_API_KEY` |

### Code Execution

| Tool | Description | Requires |
|:-----|:------------|:---------|
| `anthropic_code_execution` | Run code via Anthropic | `ANTHROPIC_API_KEY` |
| `openai_code_interpreter` | Run code via OpenAI | `OPENAI_API_KEY` |

### RAG (Retrieval Augmented Generation)

| Tool | Description | Requires |
|:-----|:------------|:---------|
| `pdf_rag` | Query PDF documents | Configuration |
| `arxiv_retriever` | Search arXiv papers | *(none)* |
| `wikipedia_rag` | Search Wikipedia | *(none)* |
| `webpage_rag` | Extract content from web pages | Configuration |
| `confluence_rag` | Search Confluence spaces | Confluence credentials |

### Communication

| Tool | Description | Requires |
|:-----|:------------|:---------|
| `gmail_toolkit` | Read/send Gmail | Google OAuth |
| `send_gmail_message_with_attachment` | Send Gmail with files | Google OAuth |

### HTTP

| Tool | Description | Requires |
|:-----|:------------|:---------|
| `requests_get` | HTTP GET requests | *(none)* |
| `requests_post` | HTTP POST requests | *(none)* |
| `requests_toolkit` | Full HTTP toolkit | *(none)* |

### Date/Time

| Tool | Description | Requires |
|:-----|:------------|:---------|
| `current_date_time` | Get current date and time | *(none)* |

### Project Management

| Tool | Description | Requires |
|:-----|:------------|:---------|
| `jira_toolkit` | Jira issue management | Jira credentials |

### Agent Management

| Tool | Description | Requires |
|:-----|:------------|:---------|
| `call_agent` | Delegate to another agent network | *(none)* |
| `agent_network_html_generator` | Visualize agent networks | *(none)* |

## Overriding Tool Arguments

You can override default tool arguments when referencing a toolbox tool:

```hocon
"tools": [
    {
        "toolbox_tool": "tavily_search",
        "tool_args": {
            "max_results": 10
        }
    }
]
```

## Custom Toolbox Files

Create your own toolbox file for project-specific tools:

```hocon
{
    "my_custom_tool": {
        "class": "my_tools.CustomTool",
        "args": {
            "api_endpoint": "https://api.example.com"
        },
        "display_as": "coded_tool"
    }
}
```

Set the environment variable to point to your file:

```bash
export AGENT_TOOLBOX_INFO_FILE="path/to/my_toolbox_info.hocon"
```

You can also specify a per-agent toolbox file in the HOCON configuration:

```hocon
{
    "name": "my_agent",
    "toolbox_info_file": "path/to/custom_toolbox.hocon",
    "tools": [
        {
            "toolbox_tool": "my_custom_tool"
        }
    ]
}
```

## Next Steps

- [Using MCP Servers](using-mcp-servers.md) -- Connect to external tool services
- [Toolbox Reference](../reference/toolbox.md) -- Complete tool catalog and schemas
- [Search Tools Comparison](../integrations/search-tools.md) -- Compare search providers
