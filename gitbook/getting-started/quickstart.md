# Quick Start

This guide walks you through running pre-built agent networks and creating your own from
scratch. By the end, you will understand the basic workflow for building with Neuro SAN.

## Running an Agent Network

### As a Library (Direct Mode)

The simplest way to interact with an agent network is to run it directly:

```bash
python -m neuro_san.client.agent_cli --agent hello_world
```

This starts an interactive chat session. Type your message and press Enter twice to send:

```
From earth, I approach a new planet and wish to send a short 2-word greeting to the new orb.

```

The agent will respond with something like "Hello, world!"

### As a Client/Server

For production use, Neuro SAN runs as a server that clients connect to.

**Start the server** in one terminal:

```bash
python -m neuro_san.service.main_loop.server_main_loop
```

**Start the client** in another terminal:

```bash
python -m neuro_san.client.agent_cli --http --agent hello_world
```

The `--http` flag tells the client to connect to the server over HTTP instead of running
the agent directly.

## Understanding hello\_world

Let's look at what makes this agent network work. Open the file
`neuro_san/registries/hello_world.hocon`:

```hocon
{
    "llm_config": {
        "model_name": "gpt-4o"
    },
    "tools": [
        {
            "name": "greeter_front_man",
            "function": {
                "description": "I can help you to make a terse announcement.
                    Tell me what your target audience is, and what sentiment
                    you would like to relate."
            },
            "instructions": "You are tasked with making a terse announcement.
                You will be given a target audience and a sentiment.
                You will use the announcement_maker tool to construct the
                announcement.",
            "tools": ["announcement_maker"]
        },
        {
            "name": "announcement_maker",
            "function": {
                "description": "Makes a terse announcement given instructions.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "instructions": {
                            "type": "string",
                            "description": "Instructions for the announcement."
                        }
                    },
                    "required": ["instructions"]
                }
            },
            "instructions": "Make an announcement per the given instructions.
                Keep it short. Two words."
        }
    ]
}
```

This file defines an agent network with two agents:

1. **greeter\_front\_man** -- The "Front Man" agent that handles user interaction. It receives
   the user's request and delegates to the announcement\_maker.
2. **announcement\_maker** -- A downstream agent that creates the actual greeting.

Key observations:

- The first agent in the `tools` list is always the **Front Man** (the entry point)
- Agents reference other agents by name in their `tools` list
- Each agent has `instructions` (system prompt) and a `function` (what it advertises to callers)
- The `llm_config` at the top applies to all agents unless overridden

## Creating Your First Agent Network

Let's create a simple agent network from scratch.

### Step 1: Create the HOCON File

Create a file called `my_assistant.hocon` in the `neuro_san/registries/` directory:

```hocon
{
    "llm_config": {
        "model_name": "gpt-4o"
    },
    "tools": [
        {
            "name": "my_assistant",
            "function": {
                "description": "I am a helpful assistant that can answer
                    questions about any topic you choose."
            },
            "instructions": "You are a friendly and knowledgeable assistant.
                Answer questions clearly and concisely.
                If you are unsure about something, say so honestly."
        }
    ]
}
```

This is the simplest possible agent network: a single agent with no sub-agents or tools.

### Step 2: Register It in the Manifest

Open `neuro_san/registries/manifest.hocon` and add your new agent:

```hocon
{
    "my_assistant.hocon": true
}
```

### Step 3: Run It

```bash
python -m neuro_san.client.agent_cli --agent my_assistant
```

Ask it anything:

```
What are the three laws of robotics?

```

### Step 4: Add a Sub-Agent

Now let's make it more interesting by adding a specialized sub-agent. Update
`my_assistant.hocon`:

```hocon
{
    "llm_config": {
        "model_name": "gpt-4o"
    },
    "tools": [
        {
            "name": "my_assistant",
            "function": {
                "description": "I am a helpful assistant that can answer
                    questions and do math."
            },
            "instructions": "You are a friendly assistant.
                When users ask math questions, delegate to the math_helper.
                For other questions, answer directly.",
            "tools": ["math_helper"]
        },
        {
            "name": "math_helper",
            "function": {
                "description": "Solves math problems step by step.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "problem": {
                            "type": "string",
                            "description": "The math problem to solve."
                        }
                    },
                    "required": ["problem"]
                }
            },
            "instructions": "You are a math specialist.
                Solve math problems step by step, showing your work.
                Always verify your answer."
        }
    ]
}
```

Now your assistant delegates math questions to a specialized agent while handling other
questions itself.

## Next Steps

- [Core Concepts](../core-concepts/README.md) -- Understand how agent networks work in depth
- [Neuro SAN Studio](studio.md) -- Use the web UI for a richer development experience
- [Guides](../guides/README.md) -- Learn how to build more complex agent networks
