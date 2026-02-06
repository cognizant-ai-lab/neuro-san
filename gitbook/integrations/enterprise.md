# Enterprise Integrations

Neuro SAN integrates with enterprise platforms for deploying agent networks within
existing business infrastructure.

## Salesforce Agentforce

Neuro SAN agent networks can be exposed as skills within Salesforce Agentforce.
This enables Salesforce agents to delegate tasks to Neuro SAN networks.

### How It Works

1. Neuro SAN serves the agent network as an MCP tool or REST API
2. Salesforce Agentforce calls the Neuro SAN endpoint as an external action
3. The agent network processes the request and returns results
4. Agentforce incorporates the results into its conversation

## Google Agentspace

Neuro SAN networks can be integrated with Google Agentspace as custom tools,
enabling enterprise search and knowledge management agents to leverage Neuro SAN
capabilities.

## ServiceNow AI Agents

Integration with ServiceNow allows Neuro SAN agent networks to handle IT service
management tasks, ticket routing, and automated resolution.

## Jira

The built-in `jira_toolkit` toolbox tool provides direct Jira integration:

```bash
export JIRA_API_TOKEN="your-token"
export JIRA_USERNAME="your-email"
export JIRA_INSTANCE_URL="https://your-instance.atlassian.net"
```

```hocon
{
    "name": "project_manager",
    "instructions": "Help manage Jira tickets and sprints.",
    "tools": [{"toolbox_tool": "jira_toolkit"}]
}
```

## CrewAI (A2A Protocol)

Neuro SAN supports integration with CrewAI through the Agent-to-Agent (A2A) protocol,
enabling interoperability between different multi-agent frameworks.

## Next Steps

- [MCP Integration](mcp.md) -- Protocol-level integration
- [Using the Toolbox](../guides/using-toolbox.md) -- Using built-in tool integrations
- [Deployment](../deployment/README.md) -- Production deployment
