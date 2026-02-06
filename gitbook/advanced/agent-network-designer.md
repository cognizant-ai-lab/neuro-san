# Agent Network Designer

The **Agent Network Designer** is a meta-agent that creates new agent networks from
natural language descriptions. Instead of writing HOCON manually, you describe what you
want and the designer generates the configuration automatically.

## How It Works

The designer is itself an agent network with specialized sub-agents:

```
Agent Network Designer (Front Man)
├── Agent Network Editor
│   ├── create_new_network
│   ├── add_agent_to_network
│   ├── remove_agent_from_network
│   └── validate_structure
├── Agent Network Instructions Editor
├── Agent Network Query Generator
└── Persist Agent Network
```

### Workflow

1. **You describe** what you want the network to do in natural language
2. **The Editor** creates the network structure (agents, tools, hierarchy)
3. **The Instructions Editor** generates system prompts for each agent
4. **The Query Generator** creates sample queries for testing
5. **Persist Agent Network** validates and saves the HOCON file

## Using the Designer

### Via CLI

```bash
python -m neuro_san.client.agent_cli --agent agent_network_designer
```

Then describe what you want:

```
Create an agent network that helps users plan meals based on dietary
restrictions and available ingredients. It should have specialists for
nutrition, recipe suggestions, and shopping lists.
```

### Via Web UI

In Neuro SAN Studio, select "agent\_network\_designer" from the agent dropdown
and chat with it through the web interface.

## Output

The designer generates:

1. A complete HOCON configuration file saved to `registries/generated/`
2. An updated manifest entry
3. Sample queries you can use to test the new network

## Persistence Options

### File System (Default)

The generated HOCON file is saved to `registries/generated/` and registered in the
manifest. The network is available immediately after the server reloads.

### Reservations (Temporary)

For testing, the designer can create a temporary network via the Reservations system.
Temporary networks have a limited lifetime and are automatically cleaned up.

## Limitations

- The designer works best with clear, specific descriptions
- Complex business logic may require manual refinement of the generated HOCON
- CodedTools must be written manually -- the designer creates the agent structure and
  instructions but cannot generate Python code

## Next Steps

- [Reservations](reservations.md) -- Temporary network lifecycle management
- [Creating Agent Networks](../guides/creating-agent-networks.md) -- Manual approach
