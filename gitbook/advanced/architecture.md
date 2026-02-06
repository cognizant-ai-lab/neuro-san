# Architecture Overview

This page describes the internal architecture of Neuro SAN for developers who want to
understand how the framework works under the hood.

## Three-Tier Execution Model

Neuro SAN separates concerns into three tiers:

```
┌─────────────────────────────────────────────────────────────┐
│                     Client Sessions                         │
│  AgentCli │ DirectAgentSession │ HttpServiceAgentSession    │
├─────────────────────────────────────────────────────────────┤
│                   Chat Orchestration                        │
│  DataDrivenChatSession │ AgentToolRegistry                  │
├─────────────────────────────────────────────────────────────┤
│                   LLM Execution Context                     │
│  LangChainRunContext │ LlmFactory │ BaseToolFactory         │
└─────────────────────────────────────────────────────────────┘
```

### Tier 1: Client Sessions

The client layer provides multiple interfaces for interacting with agent networks:

- **DirectAgentSession** -- In-process execution (no network)
- **HttpServiceAgentSession** -- REST/HTTP client
- **McpServiceAgentSession** -- MCP protocol client
- **AgentCli** -- Command-line interactive interface

All clients implement the `AgentSession` interface, providing a uniform API regardless
of the connection method.

### Tier 2: Chat Orchestration

The orchestration layer manages conversations and agent coordination:

- **DataDrivenChatSession** -- The main orchestrator. Sets up the Front Man, manages
  conversation state, coordinates streaming responses, and handles resource cleanup.
- **AgentToolRegistry** -- Loads agent network configurations from HOCON files and
  creates agent instances (CallableActivations) on demand.
- **ActivationFactory** -- Creates active agent instances that can process messages
  and invoke tools.

### Tier 3: LLM Execution Context

The execution layer handles actual LLM interactions:

- **LangChainRunContext** -- Manages the lifecycle of LLM interactions, including
  resource creation, message submission, tool output handling, and cleanup.
- **DefaultLlmFactory** -- Creates LLM instances from configuration, resolving
  provider-specific settings and fallback chains.
- **BaseToolFactory** -- Creates LangChain tool instances from agent specs, handling
  internal agents, coded tools, toolbox tools, and external agents.

## Request Flow

When a user sends a message, the following sequence occurs:

```
1. Client sends message via AgentSession.streaming_chat()
2. Server creates/resumes DataDrivenChatSession
3. DataDrivenChatSession sets up Front Man agent
4. LangChainRunContext creates LLM resources for Front Man
5. Message is submitted to the LLM
6. LLM decides to respond directly or call tools
7. If tools are called:
   a. BaseToolFactory creates tool instances
   b. For sub-agents: recursive LangChainRunContext is created
   c. For CodedTools: Python invoke() is called
   d. Tool results are returned to the LLM
   e. LLM incorporates results and may call more tools
8. Final response streams back through the session
9. Resources are cleaned up
```

## Agent Network Graph

Agent networks are loaded as directed acyclic graphs (DAGs):

```
AgentToolRegistry
  └── loads HOCON file
      └── creates AgentNetwork
          ├── metadata
          ├── llm_config (default)
          └── tools[]
              ├── Agent A (Front Man)
              │   ├── function description
              │   ├── instructions
              │   ├── llm_config (override)
              │   └── tools: [B, C]
              ├── Agent B
              │   ├── function + parameters
              │   ├── instructions
              │   └── coded_tool: "..."
              └── Agent C
                  ├── function + parameters
                  └── instructions
```

## Service Layer

The server exposes agents through multiple protocols simultaneously:

```
ServerMainLoop
├── HttpServer (Tornado)
│   ├── /streaming_chat   -- Chat with agents
│   ├── /function         -- Get agent descriptions
│   └── /mcp             -- MCP protocol endpoint
├── gRPC Service
│   └── AgentService      -- gRPC streaming
└── AgentNetworkStorage
    ├── Public agents     -- Accessible by all clients
    └── Protected agents  -- Internal-only agents
```

### Hot Reload

The server includes a `StorageWatcher` that monitors the manifest file and agent HOCON
files for changes. When modifications are detected:

1. The watcher reads the updated manifest
2. New/modified agent networks are loaded
3. Removed networks are unloaded
4. The `AgentStateListener` interface notifies the HTTP server
5. The allowed agents list is updated

## LLM Management

The LLM factory system uses a layered configuration approach:

```
Environment Variables
  └── User llm_info.hocon (AGENT_LLM_INFO_FILE)
      └── Default llm_info.hocon (built-in)
          └── Agent HOCON llm_config
              └── Resolved LLM Configuration
```

Each layer can override or extend the previous one. The final resolved configuration
determines which LangChain class to instantiate and with what parameters.

### Provider Policies

Each LLM provider has an `LlmPolicy` implementation that handles provider-specific
creation and cleanup logic:

- `StandardLangChainLlmPolicy` -- OpenAI, Anthropic
- `GeminiLlmPolicy` -- Google Gemini
- `OllamaLlmPolicy` -- Local Ollama
- `BedrockLlmPolicy` -- Amazon Bedrock

## Journal System

Neuro SAN uses a three-tier journal hierarchy for tracking messages through the agent
network:

```
OriginatingJournal
  └── InterceptingJournal
      └── Base Journal
```

- **OriginatingJournal** -- Manages the overall chat history and adds origin context
- **InterceptingJournal** -- Adds agent identification (origin path) to each message
- **Base Journal** -- Handles the actual message storage and streaming

The `origin` field on messages traces the path through the agent hierarchy, enabling
debugging and audit trails.

## Next Steps

- [Extending the Framework](extending.md) -- Add new providers and capabilities
- [Contributing](contributing.md) -- Development workflow
