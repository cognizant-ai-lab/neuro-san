# Writing CodedTools

CodedTools are custom Python classes that give agents the ability to execute code, call
APIs, and interact with external systems. This guide covers creating, registering, and
testing CodedTools.

## The CodedTool Interface

Every CodedTool implements the `CodedTool` interface from `neuro_san.interfaces.coded_tool`:

```python
from neuro_san.interfaces.coded_tool import CodedTool


class MyTool(CodedTool):

    def invoke(self, args: dict, sly_data: dict) -> dict:
        # Your logic here
        return {"response": "result"}
```

**Parameters:**

- `args` -- Dictionary of arguments provided by the LLM based on the function parameters
  defined in the HOCON file
- `sly_data` -- Dictionary of private data passed through the agent network (not visible
  to the LLM)

**Return value:** A dictionary. At minimum, include a `"response"` key with the text result.
Optionally include `"sly_data"` to pass updated sly data upstream.

## Step-by-Step: Weather Lookup Tool

### 1. Create the Python File

Create `coded_tools/weather/weather_lookup.py`:

```python
import os
import json
import urllib.request

from neuro_san.interfaces.coded_tool import CodedTool


class WeatherLookup(CodedTool):

    def invoke(self, args: dict, sly_data: dict) -> dict:
        city = args.get("city", "")
        if not city:
            return {"response": "Please provide a city name."}

        api_key = os.environ.get("WEATHER_API_KEY", "")
        if not api_key:
            return {"response": "Weather API key not configured."}

        url = (
            f"https://api.weatherapi.com/v1/current.json"
            f"?key={api_key}&q={city}"
        )
        with urllib.request.urlopen(url) as resp:
            data = json.loads(resp.read())

        condition = data["current"]["condition"]["text"]
        temp_f = data["current"]["temp_f"]
        humidity = data["current"]["humidity"]

        return {
            "response": (
                f"Weather in {city}: {condition}, "
                f"{temp_f}°F, {humidity}% humidity."
            )
        }
```

### 2. Create the HOCON Configuration

Create `registries/weather_assistant.hocon`:

```hocon
{
    "llm_config": {
        "model_name": "gpt-4o"
    },
    "tools": [
        {
            "name": "weather_assistant",
            "function": {
                "description": "I provide current weather information
                    for any city in the world."
            },
            "instructions": "You are a weather assistant.
                When users ask about weather, use the weather_lookup tool
                to get current conditions. Present the information clearly.",
            "tools": ["weather_lookup"]
        },
        {
            "name": "weather_lookup",
            "function": {
                "description": "Looks up current weather for a city.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {
                            "type": "string",
                            "description": "City name to look up."
                        }
                    },
                    "required": ["city"]
                }
            },
            "coded_tool": "coded_tools.weather.weather_lookup.WeatherLookup"
        }
    ]
}
```

### 3. Register in the Manifest

Add to `registries/manifest.hocon`:

```hocon
{
    "weather_assistant.hocon": true
}
```

### 4. Run It

```bash
export WEATHER_API_KEY="your-key"
python -m neuro_san.client.agent_cli --agent weather_assistant
```

## Working with Sly Data

CodedTools can read and write sly data for passing structured information:

```python
class OrderProcessor(CodedTool):

    def invoke(self, args: dict, sly_data: dict) -> dict:
        user_id = sly_data.get("user_id")
        if not user_id:
            return {"response": "No user ID found. Cannot process order."}

        order_id = self._create_order(user_id, args.get("items", []))

        sly_data["order_id"] = order_id
        sly_data["order_status"] = "pending"

        return {
            "response": f"Order {order_id} created successfully.",
            "sly_data": sly_data
        }

    def _create_order(self, user_id: str, items: list) -> str:
        # Business logic here
        return "ORD-12345"
```

## Async CodedTools

For I/O-bound operations (HTTP calls, database queries), use async:

```python
import aiohttp

from neuro_san.interfaces.coded_tool import CodedTool


class AsyncApiCaller(CodedTool):

    async def async_invoke(self, args: dict, sly_data: dict) -> dict:
        url = args.get("url", "")
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                data = await response.json()

        return {"response": json.dumps(data)}
```

When `async_invoke` is defined, the framework uses it instead of `invoke`.

## Tool Configuration via HOCON

Pass static configuration to your tool through the HOCON file:

```hocon
{
    "name": "database_query",
    "function": {
        "description": "Queries the product database.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "SQL query to execute."
                }
            },
            "required": ["query"]
        }
    },
    "coded_tool": "coded_tools.db.database_query.DatabaseQuery",
    "tool_args": {
        "database_url": "postgresql://localhost/products",
        "max_results": 100
    }
}
```

Access `tool_args` values in your tool through the `args` dictionary -- they are merged
with the LLM-provided arguments.

## File Organization

Organize your coded tools by domain:

```
coded_tools/
├── weather/
│   ├── __init__.py
│   └── weather_lookup.py
├── orders/
│   ├── __init__.py
│   ├── order_processor.py
│   └── order_status.py
└── integrations/
    ├── __init__.py
    └── slack_notifier.py
```

Set the `AGENT_TOOL_PATH` environment variable to tell Neuro SAN where to find your tools:

```bash
export AGENT_TOOL_PATH="./coded_tools"
```

## Best Practices

1. **Keep tools focused.** Each tool should do one thing well.
2. **Handle errors gracefully.** Return informative error messages instead of raising
   exceptions.
3. **Use sly\_data for sensitive information.** Never put credentials in args.
4. **Use async for I/O.** Prefer `async_invoke` for network calls and file operations.
5. **Don't modify the `args` dictionary.** Treat it as read-only.
6. **Log important operations.** Use Python's `logging` module for debugging.

## Next Steps

- [Using the Toolbox](using-toolbox.md) -- Pre-built tools that don't require coding
- [Sly Data](../core-concepts/sly-data.md) -- Deep dive into the sly data mechanism
- [Toolbox Reference](../reference/toolbox.md) -- Complete tool catalog
