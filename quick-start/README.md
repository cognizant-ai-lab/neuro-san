# Neuro SAN Quick Start Scripts

This folder contains easy-to-use startup scripts for launching the Neuro SAN server for this repo and client on different operating systems. We hope you will eventually create your own networks on your own servers for your own clients in your own repo. Enjoy!

## Quick Start

### macOS / Linux

**Start the server:**
```bash
./quick-start/start-server.sh
```

**Start the client (in another terminal):**
```bash
./quick-start/start-client.sh
```

### Windows

**Start the server:**
```cmd
quick-start\start-server.bat
```

**Start the client (in another terminal):**
```cmd
quick-start\start-client.bat
```

## What These Scripts Do

### Server Scripts (`start-server.sh` / `start-server.bat`)

1. ✅ Create fresh virtual environment (removes existing one to avoid outdated dependencies)
2. ✅ Activate virtual environment
3. ✅ Set PYTHONPATH
4. ✅ Install dependencies
5. ✅ Enable CORS headers (for web applications)
6. ✅ Check if port is available (exits with helpful error if port is in use)
7. ✅ Start the Neuro SAN server on port 8080 (configurable via `AGENT_HTTP_PORT`)

### Client Scripts (`start-client.sh` / `start-client.bat`)

1. ✅ Activate virtual environment
2. ✅ Set PYTHONPATH
3. ✅ Start the CLI client with specified agent

## Client Usage

**Note:** These scripts are convenience wrappers around `agent_cli`. For more control over command-line options and advanced usage, use `python -m neuro_san.client.agent_cli` directly (run with `--help` to see all available options).

### Direct Mode (No Server Required)
```bash
# macOS/Linux
./quick-start/start-client.sh hello_world

# Windows
quick-start\start-client.bat hello_world
```

### Server Mode (Connects to Running Server)
```bash
# macOS/Linux
./quick-start/start-client.sh hello_world --http

# Windows
quick-start\start-client.bat hello_world --http
```

## Available Agents

The agents included in this repository are primarily for testing the neuro-san. For comprehensive tutorials, examples, and a showcase of agent capabilities, see the **[neuro-san-studio](https://github.com/cognizant-ai-lab/neuro-san-studio)** repository.

To see all available agents:

**Query the server:**
```bash
curl http://localhost:8080/api/v1/list
```

**Or use the CLI:**
```bash
python -m neuro_san.client.agent_cli --list
```

## Environment Variables

### Required
At least one LLM provider API key is required (depending on which agents you're using):
- `OPENAI_API_KEY` - For OpenAI models
- `ANTHROPIC_API_KEY` - For Anthropic/Claude models
- `GOOGLE_API_KEY` - For Google/Gemini models
- `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` - For AWS Bedrock models
- Other provider-specific credentials

### Optional
- `AGENT_HTTP_PORT` - Server port (default: 8080)
- `AGENT_SERVER_NAME` - Server name for health reporting

For a complete list of all configurable environment variables, see the [`neuro_san/deploy/Dockerfile`](../neuro_san/deploy/Dockerfile) (search for "ENV AGENT_").

## Troubleshooting

### Virtual Environment Issues
Delete the `.venv` or `venv` folder and run the script again to recreate it.

### Missing Dependencies
The scripts automatically install dependencies, but you can manually run:
```bash
pip install -r requirements.txt
```

### Port Already in Use
The startup scripts automatically check if the port is in use and provide helpful instructions if there's a conflict. You can also change the port by setting the `AGENT_HTTP_PORT` environment variable:

```bash
# macOS/Linux
export AGENT_HTTP_PORT=8081
./quick-start/start-server.sh

# Windows
set AGENT_HTTP_PORT=8081
quick-start\start-server.bat
```

## Server Endpoints

Once the server is running:
- **Server URL:** http://localhost:8080
- **Health Check:** http://localhost:8080/health
- **OpenAPI Spec:** http://localhost:8080/api/v1/docs

### Get the OpenAPI Specification

To retrieve the complete OpenAPI specification:

```bash
curl http://localhost:8080/api/v1/docs
```

Or view it formatted:
```bash
curl http://localhost:8080/api/v1/docs | python -m json.tool
```

You can also find the OpenAPI spec source file at:
[`neuro_san/api/grpc/agent_service.json`](../neuro_san/api/grpc/agent_service.json)

