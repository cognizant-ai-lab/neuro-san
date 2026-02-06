# Tools and CodedTools

**Tools** extend what agents can do beyond text generation. They give agents the ability to
execute code, call APIs, search the web, read files, and interact with external systems.

## Types of Tools

Neuro SAN supports several types of tools:

| Type | Description | Requires Code? |
|:-----|:------------|:---------------|
| **Sub-agents** | Other agents in the network | No |
| **CodedTools** | Custom Python classes | Yes |
| **Toolbox tools** | Pre-configured reusable tools | No |
| **LangChain tools** | Tools from the LangChain ecosystem | No |
| **MCP servers** | External services via Model Context Protocol | No |

## Sub-Agents as Tools

The most basic "tool" is another agent. When you list agent names in an agent's `tools`
array, those agents become callable tools:

```hocon
{
    "name": "front_man",
    "tools": ["researcher", "writer", "reviewer"]
}
```

The LLM decides when to call each sub-agent based on its `function.description`.

## CodedTools

CodedTools are custom Python classes that agents can invoke. They are the primary way
to add real-world capabilities to your agents.

### Creating a CodedTool

1. Create a Python file in your `coded_tools/` directory
2. Implement the `CodedTool` interface

```python
from neuro_san.interfaces.coded_tool import CodedTool


class WeatherLookup(CodedTool):

    def invoke(self, args: dict, sly_data: dict) -> dict:
        city = args.get("city", "unknown")
        weather = self._fetch_weather(city)

        return {
            "response": f"The weather in {city} is {weather['condition']}, "
                       f"{weather['temp']}°F."
        }

    def _fetch_weather(self, city: str) -> dict:
        # Call an external weather API
        ...
```

### Registering a CodedTool

Reference your CodedTool in the agent's HOCON configuration using the `coded_tool` field:

```hocon
{
    "name": "weather_agent",
    "function": {
        "description": "Looks up current weather for a city.",
        "parameters": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "The city to look up weather for."
                }
            },
            "required": ["city"]
        }
    },
    "instructions": "Look up the weather using the provided tool.",
    "coded_tool": "coded_tools.weather_lookup.WeatherLookup"
}
```

The `coded_tool` value is the fully qualified Python class path. Agents with a `coded_tool`
field are **leaf agents** -- they execute code instead of delegating to an LLM.

### CodedTool with Sly Data

CodedTools can read and write sly data:

```python
class AuthenticatedTool(CodedTool):

    def invoke(self, args: dict, sly_data: dict) -> dict:
        token = sly_data.get("auth_token")
        if not token:
            return {"response": "Authentication required."}

        result = self._call_api(token, args)
        sly_data["last_api_call"] = result["id"]

        return {
            "response": result["message"],
            "sly_data": sly_data
        }
```

### Async CodedTools

For I/O-bound operations, implement the async version:

```python
class AsyncWeatherLookup(CodedTool):

    async def invoke(self, args: dict, sly_data: dict) -> dict:
        city = args.get("city", "unknown")
        weather = await self._async_fetch_weather(city)
        return {"response": f"Weather in {city}: {weather}"}
```

## Toolbox Tools

The **Toolbox** is a catalog of pre-configured tools that can be used across agent networks
without writing code. Tools are defined in a `toolbox_info.hocon` file.

### Using a Toolbox Tool

Reference a toolbox tool by name in the agent's `tools` list:

```hocon
{
    "name": "researcher",
    "instructions": "Research topics using web search.",
    "tools": ["tavily_search"]
}
```

The tool must be defined in the `toolbox_info.hocon` file:

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

### Available Toolbox Categories

| Category | Examples |
|:---------|:---------|
| Web Search | Tavily, Brave, Google, DuckDuckGo |
| Code Execution | Python REPL, shell execution |
| Date/Time | Current date, timezone conversion |
| Email | Send email via SMTP |
| HTTP | REST API calls |
| RAG | Document retrieval and search |
| Project Management | Jira, Linear integration |

See [Toolbox Reference](../reference/toolbox.md) for the complete catalog.

## LangChain Tools

Neuro SAN can use any tool from the LangChain ecosystem. Define them in the toolbox:

```hocon
{
    "wikipedia": {
        "class": "WikipediaQueryRun",
        "display_as": "coded_tool"
    }
}
```

## MCP Servers

Agents can connect to external **MCP (Model Context Protocol)** servers to access their
tools:

```hocon
{
    "name": "file_agent",
    "instructions": "Help users manage files.",
    "mcp_servers": {
        "filesystem": {
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
        }
    }
}
```

See [MCP Integration](../integrations/mcp.md) for details.

## Next Steps

- [Guides: Writing CodedTools](../guides/coded-tools.md) -- Step-by-step guide
- [Toolbox Reference](../reference/toolbox.md) -- Complete tool catalog
- [MCP Integration](../integrations/mcp.md) -- External tool servers
