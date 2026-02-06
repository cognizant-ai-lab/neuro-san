# Agent HOCON Reference

This is the complete reference for agent network HOCON configuration files. Each file
defines an agent network with its LLM settings, shared definitions, and agent specifications.

## File Structure

```hocon
{
    "llm_config": { ... },
    "commondefs": { ... },
    "metadata": { ... },
    "tools": [ ... ]
}
```

## Top-Level Fields

### llm\_config

Default LLM configuration for all agents in the network.

| Field | Type | Required | Description |
|:------|:-----|:---------|:------------|
| `model_name` | string | Yes | Model identifier (e.g., `"gpt-4o"`) |
| `class` | string | No | LangChain class name (resolved from model name if omitted) |
| `temperature` | float | No | Sampling temperature (0.0-1.0) |
| `max_tokens` | integer | No | Maximum response tokens |
| `reasoning` | boolean | No | Enable reasoning model mode |
| `fallbacks` | array | No | List of fallback `llm_config` objects |

```hocon
"llm_config": {
    "model_name": "gpt-4o",
    "temperature": 0.7,
    "max_tokens": 4096,
    "fallbacks": [
        {
            "model_name": "claude-3-5-sonnet-20241022"
        }
    ]
}
```

### commondefs

Shared definitions for string replacement and value replacement across the file.

#### replacement\_strings

Text patterns replaced within string values. Use `{key}` syntax in strings.

```hocon
"commondefs": {
    "replacement_strings": {
        "domain": "customer service",
        "aaosa_instructions": "When you receive an inquiry: ..."
    }
}
```

Usage:

```hocon
"instructions": "You handle {domain} inquiries. {aaosa_instructions}"
```

#### replacement\_values

Complete value replacements. When a field's value matches a key, the entire value is
replaced.

```hocon
"commondefs": {
    "replacement_values": {
        "standard_function": {
            "description": "Handles a standard inquiry.",
            "parameters": {
                "type": "object",
                "properties": {
                    "inquiry": {
                        "type": "string",
                        "description": "The inquiry text."
                    }
                },
                "required": ["inquiry"]
            }
        }
    }
}
```

Usage:

```hocon
{
    "name": "my_agent",
    "function": "standard_function"
}
```

### metadata

Optional metadata about the agent network.

| Field | Type | Description |
|:------|:-----|:------------|
| `description` | string | Human-readable description of the network |
| `tags` | array | Categorization tags |

```hocon
"metadata": {
    "description": "A customer service agent network.",
    "tags": ["industry", "customer-service"]
}
```

### tools

Array of agent specifications. The **first agent** in the array is the **Front Man**
(entry point).

## Agent Specification Fields

Each agent in the `tools` array can have these fields:

### name

**Required.** Unique identifier for the agent within the network.

```hocon
"name": "my_agent"
```

### function

**Required.** Describes what the agent does. Used by calling agents (or the user) to
understand the agent's capabilities.

| Field | Type | Required | Description |
|:------|:-----|:---------|:------------|
| `description` | string | Yes | What this agent does |
| `parameters` | object | No | JSON Schema for expected arguments |

```hocon
"function": {
    "description": "Looks up weather for a given city.",
    "parameters": {
        "type": "object",
        "properties": {
            "city": {
                "type": "string",
                "description": "City name."
            }
        },
        "required": ["city"]
    }
}
```

The Front Man's `function.description` is what users see when they ask "what can you do?"

Sub-agent `function` definitions follow the
[OpenAI function calling schema](https://platform.openai.com/docs/guides/function-calling).

### instructions

**Required for LLM agents.** The system prompt that defines the agent's behavior.

```hocon
"instructions": "You are a helpful weather assistant.
    When users ask about weather, use the weather_lookup tool."
```

Multi-line strings with triple quotes:

```hocon
"instructions": """
    You are a helpful weather assistant.
    When users ask about weather, use the weather_lookup tool.
    Always include temperature and conditions in your response.
"""
```

### tools

Array of sub-agent names, toolbox tool references, or MCP tool references that this
agent can call.

```hocon
"tools": [
    "sub_agent_name",
    {"toolbox_tool": "tavily_search"},
    "mcp_tool_name"
]
```

### llm\_config

Per-agent LLM override. Same structure as the top-level `llm_config`.

```hocon
"llm_config": {
    "model_name": "o1",
    "reasoning": true
}
```

### coded\_tool

Fully qualified Python class path for a CodedTool implementation. When present, the
agent executes code instead of using an LLM.

```hocon
"coded_tool": "coded_tools.weather.weather_lookup.WeatherLookup"
```

### tool\_args

Static arguments passed to a CodedTool. Merged with LLM-provided arguments at runtime.

```hocon
"tool_args": {
    "api_endpoint": "https://api.example.com",
    "timeout": 30
}
```

### mcp\_servers

MCP server definitions for this agent. Keys are server names, values are connection
configurations.

```hocon
"mcp_servers": {
    "filesystem": {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp"]
    },
    "remote_api": {
        "url": "https://mcp.example.com/v1",
        "transport": "streamable_http"
    }
}
```

### allow

Access control for sly\_data keys.

| Field | Type | Description |
|:------|:-----|:------------|
| `to_upstream.sly_data` | array | sly\_data keys this agent can pass upstream |
| `to_downstream.sly_data` | array | sly\_data keys this agent can pass downstream |
| `from_downstream.sly_data` | array | sly\_data keys accepted from downstream |
| `bubble_up_messages_from` | array | Agent paths whose messages bubble up to the user |

```hocon
"allow": {
    "to_upstream.sly_data": ["order_id", "status"],
    "to_downstream.sly_data": ["user_id", "auth_token"],
    "bubble_up_messages_from": ["/billing_agent"]
}
```

### toolbox\_info\_file

Path to a custom toolbox HOCON file for this agent. Overrides the default toolbox.

```hocon
"toolbox_info_file": "path/to/custom_toolbox.hocon"
```

## Complete Example

```hocon
{
    "llm_config": {
        "model_name": "gpt-4o",
        "temperature": 0.7,
        "fallbacks": [
            {
                "model_name": "claude-3-5-sonnet-20241022"
            }
        ]
    },
    "commondefs": {
        "replacement_strings": {
            "aaosa_instructions": """
                When you receive an inquiry:
                0. If clearly not your area, say so immediately.
                1. Always call ALL tools before declaring irrelevance.
                2. Respond based on tool results.
            """
        }
    },
    "metadata": {
        "description": "Customer service agent network.",
        "tags": ["industry", "customer-service"]
    },
    "tools": [
        {
            "name": "customer_service",
            "function": {
                "description": "I help with billing and support questions."
            },
            "instructions": """
                You are a customer service coordinator.
                {aaosa_instructions}
            """,
            "tools": ["billing_agent", "support_agent"]
        },
        {
            "name": "billing_agent",
            "function": {
                "description": "Handles billing inquiries.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "inquiry": {
                            "type": "string",
                            "description": "The billing question."
                        }
                    },
                    "required": ["inquiry"]
                }
            },
            "instructions": "Handle billing questions accurately.",
            "tools": ["account_lookup"]
        },
        {
            "name": "support_agent",
            "function": {
                "description": "Handles technical support issues.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "issue": {
                            "type": "string",
                            "description": "The technical issue."
                        }
                    },
                    "required": ["issue"]
                }
            },
            "instructions": "Troubleshoot technical issues step by step."
        },
        {
            "name": "account_lookup",
            "function": {
                "description": "Looks up account details.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "account_id": {
                            "type": "string",
                            "description": "The account ID."
                        }
                    },
                    "required": ["account_id"]
                }
            },
            "coded_tool": "coded_tools.billing.account_lookup.AccountLookup",
            "allow": {
                "to_upstream.sly_data": ["account_details"]
            }
        }
    ]
}
```
