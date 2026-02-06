# HOCON Configuration

Neuro SAN uses **HOCON** (Human-Optimized Config Object Notation) as its configuration
format. HOCON is a superset of JSON that adds features making it easier to read and write
by humans.

## Why HOCON?

Agent networks could be defined in JSON, YAML, or Python code. HOCON was chosen because it:

- Supports **comments** (JSON does not)
- Allows **multi-line strings** without escape characters
- Supports **includes** and **substitutions** for reuse
- Is familiar to anyone who knows JSON
- Keeps agent definitions data-only, not code

## HOCON Basics

### It's JSON with Extras

Any valid JSON is also valid HOCON. You can start with JSON and add HOCON features
as needed.

```hocon
{
    "name": "my_agent",
    "temperature": 0.7
}
```

### Comments

Use `#` or `//` for comments:

```hocon
{
    # This is a comment
    "name": "my_agent",
    // This is also a comment
    "temperature": 0.7
}
```

### Multi-line Strings

Use triple quotes for multi-line strings, which is especially useful for agent instructions:

```hocon
{
    "instructions": """
        You are a helpful assistant.
        Answer questions clearly and concisely.
        If you are unsure about something, say so.
    """
}
```

### Includes

Pull in definitions from other files:

```hocon
include "registries/aaosa.hocon"

{
    "tools": [
        {
            "function": ${aaosa_call}
        }
    ]
}
```

The include path should be an absolute path or relative to the project root.

### Substitutions

Reference values defined elsewhere using `${}`:

```hocon
{
    "commondefs": {
        "replacement_strings": {
            "instructions_prefix": "You are responsible for a segment of a problem."
        }
    },
    "tools": [
        {
            "instructions": "{instructions_prefix} Your specific task is..."
        }
    ]
}
```

Use `${?VARIABLE}` for optional substitutions that won't cause errors if the value
is missing:

```hocon
{
    "api_key": ${?MY_OPTIONAL_KEY}
}
```

Environment variables can also be substituted:

```hocon
{
    "api_key": ${OPENAI_API_KEY}
}
```

> **Security note:** Never hardcode secrets in HOCON files. Always use environment
> variable substitutions for API keys and credentials.

## Agent Network HOCON Structure

Every agent network HOCON file follows this general structure:

```hocon
{
    # LLM configuration (applies to all agents by default)
    "llm_config": {
        "model_name": "gpt-4o",
        "temperature": 0.7
    },

    # Optional: reusable definitions
    "commondefs": {
        "replacement_strings": { ... },
        "replacement_values": { ... }
    },

    # Optional: metadata about the network
    "metadata": {
        "description": "What this network does",
        "tags": ["example", "basic"]
    },

    # The list of agents (first one is the Front Man)
    "tools": [
        { ... },
        { ... }
    ]
}
```

### commondefs

The `commondefs` section lets you define values that are reused across the file.

**replacement\_strings** replaces text within strings using `{key}` syntax:

```hocon
"commondefs": {
    "replacement_strings": {
        "domain": "customer service"
    }
},
"tools": [
    {
        "instructions": "You handle {domain} inquiries."
        # Becomes: "You handle customer service inquiries."
    }
]
```

**replacement\_values** replaces entire values (not just text within strings):

```hocon
"commondefs": {
    "replacement_values": {
        "standard_function": {
            "description": "Handles inquiries.",
            "parameters": { ... }
        }
    }
},
"tools": [
    {
        "function": "standard_function"
        # Replaced with the full dictionary
    }
]
```

## Next Steps

- [Agent Networks](agent-networks.md) -- How agents are structured
- [Agent HOCON Reference](../reference/agent-hocon.md) -- Complete field reference
- [Manifest Reference](../reference/manifest.md) -- How to register agent networks
