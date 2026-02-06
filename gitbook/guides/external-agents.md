# External Agent Networks

Neuro SAN supports connecting agent networks that run on different servers. This enables
distributed architectures where specialized networks are maintained independently.

## How External Agents Work

An external agent is a reference to an agent network running on a different Neuro SAN
server. From the calling agent's perspective, it looks like any other sub-agent, but
the actual execution happens on the remote server.

```
Local Server                          Remote Server
┌──────────────┐                    ┌──────────────────┐
│  Front Man   │ ──── HTTP ────►    │  Banking Network │
│              │                    │  (Front Man)     │
│  tools:      │                    │    ├── accounts  │
│  - /banking  │ ◄── Response ──    │    └── transfers │
└──────────────┘                    └──────────────────┘
```

## Defining External Agents

Reference an external network by prefixing its name with `/` in the tools list:

```hocon
{
    "llm_config": {
        "model_name": "gpt-4o"
    },
    "tools": [
        {
            "name": "enterprise_assistant",
            "function": {
                "description": "I help with enterprise operations."
            },
            "instructions": "Route requests to the appropriate department.",
            "tools": ["/banking_ops", "/hr_portal"]
        }
    ]
}
```

The framework resolves external agent references at runtime by connecting to the remote
server where those networks are hosted.

## Configuration

Set the remote server address via environment variables:

```bash
export AGENT_EXTERNAL_HOST="remote-server.example.com"
export AGENT_EXTERNAL_PORT="8080"
```

Or configure per-network connection details in the agent HOCON file.

## Use Cases

- **Microservice architecture** -- Each team maintains their own agent networks
- **Scaling** -- Distribute compute-heavy networks across multiple servers
- **Security isolation** -- Keep sensitive networks on separate infrastructure
- **Shared services** -- Provide common capabilities (search, auth) as shared networks

## Next Steps

- [Memory and Conversation](memory.md) -- Maintain state across interactions
- [Deployment](../deployment/README.md) -- Deploy distributed agent services
