# Experimental multi-process service operation

> [!WARNING]
> Multi-process operation is not yet safe for every service component. Background components may run
> redundantly or contend with one another. Do not enable it for production workloads until those components
> support coordinated multi-process operation.

Start the service with:

```shell
python -m neuro_san.service.main_loop.server_main_loop
```

The supported and recommended configuration is one HTTP server process. Experimental multi-process operation
can be configured with either the
`AGENT_HTTP_SERVER_INSTANCES` environment variable or the `--http_server_instances` command-line option:

```shell
AGENT_HTTP_SERVER_INSTANCES=4 python -m neuro_san.service.main_loop.server_main_loop
```

The supported values are:

* `1`: run a single server process. This is the default outside the deployment container.
* A positive integer: run exactly that many server processes.
* `0`: run one server process per available CPU core.

## Experimental multi-process behavior

On Linux and other supported POSIX systems, neuro-san retains Tornado's existing pre-bound socket and worker
process behavior.

On macOS, neuro-san starts each worker in a fresh Python interpreter. Every worker binds the same HTTP port
with `SO_REUSEPORT`, allowing the operating system to distribute incoming connections. This avoids forking a
process after macOS system frameworks have initialized, which can otherwise cause an Objective-C runtime abort
when the first request reaches a worker.

The macOS supervisor forwards interrupt and termination signals to its workers and returns a non-zero status if
a worker fails. `OBJC_DISABLE_INITIALIZE_FORK_SAFETY` is not required.

For production deployments, use one server process per container and let the container orchestrator scale
replicas. This provides independent health checks and lifecycle management. Override the deployment container's
`AGENT_HTTP_SERVER_INSTANCES=0` default with `1` when scaling through multiple container replicas.

Temporary agent networks (Reservations) are not currently suitable for multi-process operation. Use
`AGENT_HTTP_SERVER_INSTANCES=1` when the service requires temporary agent networks.

## Related configuration

The service accepts environment variables for its command-line options. Common settings include:

* `AGENT_HTTP_PORT`: HTTP and MCP service port. The default is `8080`.
* `AGENT_HTTP_CONNECTIONS_BACKLOG`: maximum pending TCP connections. The default is `128`.
* `AGENT_HTTP_IDLE_CONNECTIONS_TIMEOUT`: idle keep-alive timeout in seconds. The default is `3600`.
* `AGENT_HEALTH_PROBE_PORT`: isolated health-probe port. Set it to `0` to disable the isolated probe server.
* `AGENT_HTTP_SERVER_INSTANCES`: number of HTTP server processes, as described above.

Run the module with `--help` for the complete command-line option list.
