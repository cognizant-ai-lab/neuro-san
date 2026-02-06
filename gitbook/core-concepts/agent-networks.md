# Agent Networks

An **agent network** is a group of LLM-powered agents that collaborate to solve a problem.
Each agent has a specific role and can delegate tasks to other agents or tools.

## Why Multiple Agents?

A single LLM can struggle with complex, multi-faceted problems. Think of it this way:
asking one person to handle customer service, technical support, billing, and inventory
management simultaneously would be overwhelming. Instead, you'd hire specialists.

Agent networks apply the same principle to LLMs. Each agent focuses on a narrow task
it can do well, and agents work together to handle the full complexity.

## Network Structure

Every agent network has at least one agent. Networks are structured as **directed acyclic
graphs (DAGs)** -- agents can delegate to other agents, but there are no circular
dependencies.

### The Front Man

The first agent in the `tools` list is the **Front Man**. This agent:

- Receives all user input
- Decides how to handle requests
- Delegates to sub-agents when needed
- Returns the final response to the user

Only the Front Man communicates directly with the client. All other agents are internal
to the network.

### Sub-Agents

Other agents in the network are **sub-agents**. They:

- Receive delegated tasks from the Front Man or other agents
- Have their own specialized instructions and capabilities
- Can further delegate to their own sub-agents or tools
- Return results upstream to their caller

### Example: A Simple Network

```
User
  │
  ▼
┌─────────────┐
│  Front Man  │  ← Receives user input, coordinates
│  (greeter)  │
└──────┬──────┘
       │
       ▼
┌─────────────────────┐
│  announcement_maker  │  ← Specialist: crafts the greeting
└─────────────────────┘
```

In the hello\_world example, the greeter Front Man receives the user's request and
delegates the actual greeting creation to the announcement\_maker agent.

### Example: A Branching Network

```
User
  │
  ▼
┌───────────┐
│ Front Man │
└─────┬─────┘
      │
      ├────────────┬────────────┐
      ▼            ▼            ▼
┌──────────┐ ┌──────────┐ ┌──────────┐
│ Agent A  │ │ Agent B  │ │ Agent C  │
│ (billing)│ │ (support)│ │ (sales)  │
└──────────┘ └────┬─────┘ └──────────┘
                  │
                  ▼
            ┌──────────┐
            │ Agent D  │
            │ (network)│
            └──────────┘
```

The Front Man can delegate to multiple specialists. Each specialist can have its own
sub-agents. The Front Man decides which agent(s) to call based on the user's request.

## How Agents Communicate

When an agent delegates to a sub-agent, it passes:

- A **text message** describing the task (via the LLM's function-calling mechanism)
- Optionally, **sly\_data** containing private data not visible to the LLM

The sub-agent processes the request and returns its result upstream. The calling agent
then incorporates the result into its own reasoning.

## Defining a Network in HOCON

Agent networks are defined entirely in HOCON configuration files. Here is the minimal
structure:

```hocon
{
    "llm_config": {
        "model_name": "gpt-4o"
    },
    "tools": [
        {
            "name": "front_man",
            "function": {
                "description": "What this network does for the user."
            },
            "instructions": "System prompt for the front man.",
            "tools": ["specialist"]
        },
        {
            "name": "specialist",
            "function": {
                "description": "What this agent does.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task": {
                            "type": "string",
                            "description": "The task to perform."
                        }
                    },
                    "required": ["task"]
                }
            },
            "instructions": "System prompt for the specialist."
        }
    ]
}
```

Key points:

- **`llm_config`** sets the default LLM for all agents
- **`tools`** is the list of agents (first one is the Front Man)
- Each agent has a **`name`**, **`function`** (what it advertises), and **`instructions`**
  (its system prompt)
- Agents reference sub-agents by name in their **`tools`** list

## Next Steps

- [HOCON Configuration](hocon.md) -- Learn the configuration format in detail
- [The AAOSA Protocol](aaosa.md) -- How agents decide relevance
- [Tools and CodedTools](tools.md) -- Extend agents with Python code
