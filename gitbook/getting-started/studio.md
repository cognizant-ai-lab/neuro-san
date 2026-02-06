# Neuro SAN Studio

[Neuro SAN Studio](https://github.com/cognizant-ai-lab/neuro-san-studio) is a hands-on
development environment built on top of the Neuro SAN library. It provides:

- A **web UI** for interacting with agent networks visually
- A large collection of **ready-to-run examples** across industries
- **Tutorials** and templates for building new agent networks
- An **Agent Network Designer** meta-agent that creates agent networks from natural language

If the Neuro SAN library is the engine, Studio is the full car with dashboard and steering wheel.

## Installation

```bash
git clone https://github.com/cognizant-ai-lab/neuro-san-studio
cd neuro-san-studio
python -m venv venv
source venv/bin/activate
export PYTHONPATH=$(pwd)
pip install -r requirements.txt
```

On Windows:

```cmd
.\venv\Scripts\activate.bat
set PYTHONPATH=%CD%
pip install -r requirements.txt
```

## Configuration

Copy the example environment file and set your API keys:

```bash
cp .env.example .env
```

Edit `.env` and set at least:

```bash
OPENAI_API_KEY=your-api-key-here
```

See the `.env.example` file for all available configuration options including keys for
Anthropic, Azure, Bedrock, Gemini, and other providers.

## Running

Start the server and web client with a single command:

```bash
python -m run
```

This launches:

- The **Neuro SAN server** (gRPC on port 30011, HTTP on port 8080)
- The **NSFlow web UI** at [http://localhost:4173/](http://localhost:4173/)
- **Phoenix observability** at [http://localhost:6006/](http://localhost:6006/) (if enabled)

Use `--help` to see all available configuration options:

```bash
python -m run --help
```

## Project Structure

```
neuro-san-studio/
├── registries/           # Agent network HOCON files
│   ├── manifest.hocon    # Registry of enabled networks
│   ├── basic/            # Simple introductory examples
│   ├── tools/            # Tool integration examples
│   ├── industry/         # Industry-specific solutions
│   └── experimental/     # Research and experimental features
├── coded_tools/          # Python tool implementations
├── toolbox/              # Shared tool catalog
├── apps/                 # Web applications (CRUSE)
├── deploy/               # Docker and deployment configs
├── tests/                # Test suite
├── docs/                 # Additional documentation
└── run.py                # Main entrypoint
```

## Exploring Examples

Studio ships with dozens of example agent networks organized by category:

- **Basic** -- Simple networks for learning (music\_nerd, hello\_world, coffee\_finder)
- **Tools** -- Integration with search, RAG, email, code execution
- **Industry** -- Domain solutions (airline, banking, telco, insurance, retail)
- **Experimental** -- Research features (Agent Network Designer, Copy Cat, CRUSE)

Browse the available agents in the web UI or check
[Examples](../examples/README.md) for a complete listing.

## Logs

When running, logs are written to:

- `logs/server.log` -- Server logs
- `logs/nsflow.log` -- Web client logs
- `logs/thinking_dir/` -- Per-agent reasoning logs

## Next Steps

- [Core Concepts](../core-concepts/README.md) -- Understand the fundamentals
- [Examples](../examples/README.md) -- Explore the full catalog of agent networks
- [Guides](../guides/README.md) -- Build your own agent networks
