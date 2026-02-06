# The AAOSA Protocol

**AAOSA** (Agent-as-a-Service Architecture) is a communication protocol used in Neuro SAN
agent networks. It defines how agents decide whether they are the right one to handle
a particular request.

## The Problem AAOSA Solves

When a Front Man agent has multiple sub-agents, it needs to figure out which ones are
relevant. For example, a customer service network might have agents for billing, technical
support, and sales. When a user asks about a refund, only the billing agent is relevant.

AAOSA provides a standard pattern for this decision-making process.

## How It Works

The AAOSA protocol follows three steps:

1. **Check relevance** -- Each agent first determines if the request is within its domain.
   If it clearly is not, the agent declares itself irrelevant immediately.

2. **Consult all tools** -- If the request *might* be relevant, the agent calls *all* of
   its sub-agents before making a decision. This ensures no relevant information is missed.

3. **Respond or declare irrelevance** -- Based on what the sub-agents return, the agent
   either provides a response or declares itself irrelevant.

## AAOSA Instructions Template

The typical AAOSA instructions pattern looks like this:

```hocon
"instructions": """
    You are responsible for a segment of a problem.
    Only answer inquiries that are directly within your domain.

    When you receive an inquiry:
    0. If you are clearly not the right agent for this inquiry,
       immediately respond that you are not relevant.
    1. If there is any chance the inquiry is relevant to you,
       always call ALL of your tools before declaring irrelevance.
    2. Based on what your tools return, either provide an answer
       or declare that you are not the right agent.
"""
```

## Example: Coffee Finder

The coffee\_finder example demonstrates AAOSA well. The network has a Front Man that
delegates to multiple coffee-finding agents:

```
User: "Where can I get coffee?"
  │
  ▼
┌──────────────────┐
│   Coffee Finder  │  ← Front Man (uses AAOSA)
│   (Front Man)    │
└───┬─────┬────┬───┘
    │     │    │
    ▼     ▼    ▼
┌──────┐┌──────┐┌──────────────┐
│Coffee││Café  ││ Vending      │
│Shop  ││teria ││ Machine      │
└──────┘└──────┘└──────────────┘
```

When the user asks "Where can I get coffee?", the Front Man consults all three agents.
Depending on context (time of day, location), different agents may be more relevant.
The Front Man uses AAOSA to gather all their responses before deciding which option
to recommend.

## Using commondefs for AAOSA

Since AAOSA instructions are reused across agents, it's common to define them in
`commondefs`:

```hocon
{
    "commondefs": {
        "replacement_strings": {
            "aaosa_instructions": """
                When you receive an inquiry:
                0. If you are clearly not the right agent, say so.
                1. Always call ALL tools before declaring irrelevance.
                2. Respond based on what your tools return.
            """
        }
    },
    "tools": [
        {
            "name": "front_man",
            "instructions": """
                You coordinate customer inquiries.
                {aaosa_instructions}
            """,
            "tools": ["billing", "support", "sales"]
        }
    ]
}
```

Using HOCON's include feature, Neuro SAN Studio provides a shared `aaosa.hocon` file
that you can include directly:

```hocon
include "registries/aaosa.hocon"
```

## When to Use AAOSA

Use AAOSA when:

- Multiple agents provide overlapping services
- The correct agent depends on runtime context
- You want agents to self-select rather than hard-coding routing logic

For simple hierarchies where delegation is straightforward (e.g., "always send math
questions to the math agent"), explicit delegation in the Front Man's instructions
is simpler and sufficient.

## Next Steps

- [Sly Data](sly-data.md) -- Private data channels between agents
- [Examples: Coffee Finder](../examples/README.md) -- See AAOSA in action
