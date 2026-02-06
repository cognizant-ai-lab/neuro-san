# Glossary

Key terms and definitions used throughout the Neuro SAN documentation.

## A

### AAOSA (Agent-as-a-Service Architecture)
A communication protocol where multiple agents can provide similar services. When a request
arrives, each agent determines its own relevance before responding. This enables flexible
routing without hard-coded dispatch logic.

### Agent
An LLM-powered unit within a network that has its own instructions (system prompt),
function description, and optionally sub-agents or tools. Agents are defined in HOCON
configuration files.

### Agent Network
A collection of agents configured to work together on a problem. Networks are structured
as directed acyclic graphs (DAGs) where agents delegate tasks to sub-agents.

### Agent Network Designer
A meta-agent in Neuro SAN Studio that creates new agent networks from natural language
descriptions. It generates HOCON configuration files automatically.

## C

### chat\_context
A serializable dictionary containing conversation state (including chat histories). Returned
with each response and passed back with the next request to maintain conversation continuity
across stateless interactions.

### CodedTool
A custom Python class that implements the `CodedTool` interface. Agents invoke coded tools
to execute arbitrary code, call APIs, or interact with external systems. Coded tools receive
both LLM-generated arguments and sly\_data.

### commondefs
A section in HOCON configuration files for defining reusable values. Contains
`replacement_strings` (text substitution within strings) and `replacement_values`
(full value replacement).

## D

### DAG (Directed Acyclic Graph)
The structure of an agent network. Agents can delegate to sub-agents (directed), but there
are no circular dependencies (acyclic). This ensures requests always terminate.

### Direct Mode
Running an agent network in-process without a server. Useful for development and testing.
Activated by omitting the `--http` flag in the CLI.

## E

### External Agent
An agent defined on a different server, referenced by URL in the tools array. Enables
distributed agent networks that span multiple services.

## F

### Front Man
The entry-point agent in a network that receives all user input. Always the first agent
in the `tools` list. Only the Front Man communicates directly with clients.

## G

### gRPC
One of the server protocols supported by Neuro SAN. Uses Protocol Buffers for efficient
binary communication. Runs on port 30011 by default.

## H

### HOCON (Human-Optimized Config Object Notation)
The configuration format used to define agent networks, manifests, LLM settings, and
toolbox configurations. A superset of JSON with support for comments, multi-line strings,
includes, and substitutions.

### Hot Reload
The server's ability to detect changes to HOCON configuration files and reload agent
networks without restarting. Controlled by the `--manifest-update-period-seconds` flag.

## L

### LLM (Large Language Model)
The AI model that powers each agent's reasoning. Neuro SAN supports multiple providers
including OpenAI, Anthropic, Google Gemini, Azure OpenAI, Amazon Bedrock, and Ollama.

### llm\_config
A HOCON section that specifies which LLM model to use and its parameters (temperature,
max tokens, etc.). Can be set at the network level (default for all agents) or per-agent.

## M

### Manifest
A HOCON file (`manifest.hocon`) that registers which agent networks are available. Maps
HOCON file paths to boolean or dictionary values controlling whether they are served,
public, or exposed via MCP.

### MCP (Model Context Protocol)
An open protocol for connecting LLMs to external tools and data sources. Neuro SAN can
both serve agent networks as MCP tools and consume external MCP servers.

## N

### Neuro SAN
NeuroAI data-driven System for multi-Agent Networks. The core library for building
data-driven multi-agent AI systems.

### Neuro SAN Studio
The development environment built on Neuro SAN. Provides a web UI, examples, tutorials,
and an Agent Network Designer.

### NSFlow
The web UI client included with Neuro SAN Studio. Provides a visual interface for
interacting with agent networks.

## O

### origin
A list tracking the provenance of messages through the agent hierarchy. Each entry contains
the tool name and instantiation index, enabling tracing of message sources.

## R

### Reservations
Temporary agent networks with a limited lifetime. Created programmatically and
automatically cleaned up after expiration. Used by the Agent Network Designer and
Copy Cat features.

## S

### sly\_data
A side-channel dictionary that passes structured data between agents and tools without
exposing it to the LLM. Used for authentication tokens, user IDs, configuration, and
other data that should not influence LLM reasoning.

### Streaming
The ability to receive partial responses as they are generated, rather than waiting for
the complete response. Supported by the HTTP and gRPC protocols.

## T

### Toolbox
A catalog of pre-configured, reusable tools defined in `toolbox_info.hocon`. Agents
reference toolbox tools by name without needing custom code.

### ToolCaller
An interface for tools that invoke agents or LLMs as functions. Provides methods for
making tool function calls and inspecting agent specifications.
