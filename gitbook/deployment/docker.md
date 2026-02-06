# Docker Deployment

Neuro SAN provides Docker support for containerized deployment.

## Building the Image

From the deploy directory:

```bash
cd neuro_san/deploy
./build.sh
```

This creates a Docker image based on Python 3.13 slim with all dependencies installed.

## Running Locally

```bash
cd neuro_san/deploy
./run.sh
```

The container starts the Neuro SAN server with:

- gRPC on port 30011
- HTTP on port 8080

## Manual Docker Commands

### Build

```bash
docker build --file neuro_san/deploy/Dockerfile --tag neuro-san .
```

### Run

```bash
docker run \
    --publish 8080:8080 \
    --publish 30011:30011 \
    --env OPENAI_API_KEY="sk-..." \
    neuro-san
```

### Using an Environment File

```bash
docker run \
    --publish 8080:8080 \
    --publish 30011:30011 \
    --env-file .env \
    neuro-san
```

### Mounting Custom Registries

Mount your own agent network files into the container:

```bash
docker run \
    --publish 8080:8080 \
    --volume ./my_registries:/app/registries:ro \
    --volume ./my_coded_tools:/app/coded_tools:ro \
    --env-file .env \
    neuro-san
```

## Neuro SAN Studio Docker

Studio has its own Docker configuration:

```bash
cd neuro-san-studio/deploy
./build.sh
./run.sh
```

This starts the full Studio environment including the web UI.

## Dockerfile Overview

The production Dockerfile uses a multi-stage build:

1. **Build stage** -- Installs Python dependencies
2. **Runtime stage** -- Copies only what's needed for running

Key characteristics:

- Based on `python:3.13-slim`
- Non-root user for security
- Health check endpoint
- Structured JSON logging

## Production Considerations

- **API keys** -- Pass via environment variables, never bake into the image
- **Networking** -- Expose only the ports you need (HTTP 8080, gRPC 30011)
- **Volumes** -- Mount registries and tools as read-only volumes
- **Resources** -- LLM calls are I/O-bound; allocate based on concurrent users, not CPU
- **Health checks** -- The HTTP endpoint can be used for container health monitoring

## Next Steps

- [Configuration](configuration.md) -- Production environment setup
- [Security](security.md) -- Multi-user access control
- [Observability](observability.md) -- Monitoring and tracing
