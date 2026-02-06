# Toolbox Reference

The toolbox is a catalog of pre-configured tools that agents can use by name. Tools are
defined in a `toolbox_info.hocon` file.

## File Location

Set the toolbox file path:

```bash
export AGENT_TOOLBOX_INFO_FILE="path/to/toolbox_info.hocon"
```

## Tool Definition Format

Each tool entry specifies the implementation class, optional arguments, and how it should
be presented to the LLM:

```hocon
{
    "tool_name": {
        "class": "ClassName",
        "args": {
            "param1": "value1"
        },
        "display_as": "coded_tool",
        "description": "What the tool does.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The input query."
                }
            },
            "required": ["query"]
        }
    }
}
```

## Fields

| Field | Type | Required | Description |
|:------|:-----|:---------|:------------|
| `class` | string | Yes | Python class or LangChain tool class |
| `args` | object | No | Constructor arguments for the tool |
| `display_as` | string | No | How to present to the LLM (`"coded_tool"` or `"langchain"`) |
| `description` | string | No | Override the tool's default description |
| `parameters` | object | No | JSON Schema for tool arguments |

## Tool Types

### LangChain Tools

Tools from the LangChain ecosystem:

```hocon
{
    "tavily_search": {
        "class": "TavilySearchResults",
        "args": {
            "max_results": 5
        }
    }
}
```

### CodedTools

Custom Python tools:

```hocon
{
    "my_tool": {
        "class": "tools.my_tool.MyTool",
        "display_as": "coded_tool",
        "args": {
            "api_url": "https://api.example.com"
        }
    }
}
```

## Using Toolbox Tools in Agents

Reference a toolbox tool in an agent's `tools` list:

```hocon
{
    "name": "researcher",
    "tools": [
        {"toolbox_tool": "tavily_search"},
        {"toolbox_tool": "wikipedia_rag"}
    ]
}
```

Override default arguments per-agent:

```hocon
{
    "toolbox_tool": "tavily_search",
    "tool_args": {
        "max_results": 10
    }
}
```

## Per-Agent Toolbox

Specify a custom toolbox file for a specific agent:

```hocon
{
    "name": "my_agent",
    "toolbox_info_file": "path/to/custom_toolbox.hocon",
    "tools": [
        {"toolbox_tool": "custom_tool"}
    ]
}
```

## Extending the Default Toolbox

Your custom toolbox file overlays the built-in defaults. You can add new tools or
override existing ones without modifying the original file.
