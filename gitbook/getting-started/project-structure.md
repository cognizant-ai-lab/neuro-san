# Project Structure

Understanding how the Neuro SAN codebase is organized helps you navigate and extend it
effectively.

## neuro-san (Library)

The core library that powers all agent network functionality.

```
neuro-san/
├── neuro_san/
│   ├── api/                  # API definitions
│   │   └── grpc/             # Protobuf definitions (agent.proto, chat.proto)
│   ├── client/               # Client implementations
│   │   ├── agent_cli.py      # Command-line chat interface
│   │   └── hocon_validator_cli.py  # HOCON validation tool
│   ├── coded_tools/          # Built-in tool implementations
│   ├── deploy/               # Docker deployment files
│   │   ├── Dockerfile
│   │   ├── build.sh
│   │   └── run.sh
│   ├── interfaces/           # Public interfaces
│   │   ├── agent_session.py  # Session interface for clients
│   │   └── coded_tool.py     # Interface for custom tools
│   ├── internals/            # Core framework internals
│   │   ├── chat/             # Chat session management
│   │   ├── graph/            # Agent network graph and registry
│   │   └── run_context/      # LLM execution contexts
│   │       └── langchain/    # LangChain integration
│   │           ├── llms/     # LLM provider implementations
│   │           ├── mcp/      # MCP adapter
│   │           └── toolbox/  # Default toolbox definitions
│   ├── registries/           # Agent network HOCON files
│   │   └── manifest.hocon    # Central registry
│   ├── service/              # Server implementation
│   │   ├── http/             # HTTP server and handlers
│   │   ├── grpc/             # gRPC service
│   │   ├── mcp/              # MCP protocol service
│   │   └── main_loop/        # Service orchestrator
│   └── session/              # Session management
├── tests/                    # Test suite
├── docs/                     # Reference documentation
├── requirements.txt          # Runtime dependencies
└── pyproject.toml            # Project metadata
```

### Key Directories

| Directory | Purpose |
|:----------|:--------|
| `neuro_san/registries/` | Agent network HOCON configuration files |
| `neuro_san/coded_tools/` | Python tool implementations that agents can call |
| `neuro_san/interfaces/` | Public interfaces you implement (CodedTool, AgentSession) |
| `neuro_san/service/` | Server infrastructure (HTTP, gRPC, MCP) |
| `neuro_san/client/` | Client implementations and CLI |
| `neuro_san/internals/` | Framework internals (usually not modified directly) |

## neuro-san-studio (IDE)

The development environment that wraps the library with examples, tools, and a web UI.

```
neuro-san-studio/
├── registries/               # Agent network HOCON files (many examples)
│   ├── manifest.hocon        # Registry of all networks
│   ├── basic/                # Introductory examples
│   ├── tools/                # Tool integration examples
│   ├── industry/             # Industry solutions
│   └── experimental/         # Research features
├── coded_tools/              # Python tool implementations
│   ├── tools/                # General-purpose tools
│   ├── agent_network_designer/  # Meta-agent tools
│   └── cruse_agent/          # CRUSE UI tools
├── toolbox/                  # Shared tool catalog
│   └── toolbox_info.hocon    # Tool definitions
├── apps/                     # Web applications
│   └── cruse/                # Context Reactive UX
├── deploy/                   # Deployment configs
├── tests/                    # Test suite
│   ├── integration/          # Integration tests
│   └── fixtures/             # Test HOCON files
├── run.py                    # Main entrypoint
└── .env.example              # Environment configuration template
```

### Key Directories

| Directory | Purpose |
|:----------|:--------|
| `registries/` | Where you define and store agent network configurations |
| `coded_tools/` | Where custom Python tools live |
| `toolbox/` | Catalog of pre-configured, reusable tools |
| `apps/` | Web applications for agent interaction |
| `tests/fixtures/` | Data-driven test cases for agent networks |

## How They Relate

The library (`neuro-san`) provides the core framework: agent orchestration, LLM management,
server infrastructure, and the client interfaces.

The studio (`neuro-san-studio`) uses the library as a dependency and adds:

- A richer set of example agent networks
- More coded tools and integrations
- Web UI clients (NSFlow, CRUSE)
- A toolbox catalog with pre-configured tools
- Integration tests and fixtures

When building your own project, you can either:

1. **Use Studio as a starting point** -- Clone neuro-san-studio and add your own networks
   alongside the examples
2. **Use the library directly** -- Install `neuro-san` via pip and create your own project
   structure with your own registries and coded\_tools directories
