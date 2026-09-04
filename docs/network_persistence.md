# Network Persistence Modes

Agent networks created while a neuro-san server is running can be made available
in two ways: by changing the registry files on disk, or by deploying a temporary
network reservation. The producer of the network chooses the mode. For example,
Agent Network Designer uses the file-based mode by default and uses reservations
when `AGENT_NETWORK_DESIGNER_USE_RESERVATIONS=true`.

<!-- pyml disable line-length -->
| | Registry files | In-memory reservation |
| --- | --- | --- |
| Storage | Agent HOCON file and `manifest.hocon` | Server temporary-network storage |
| Server setting | `AGENT_MANIFEST_UPDATE_PERIOD_SECONDS` must be greater than `0` | No update-period setting is required |
| Lifetime | Remains available until the files are changed or removed | Expires after its reservation lifetime; the default maximum is 24 hours |
| Server restart | Survives because the server reloads the files | Lost unless external reservation storage is configured |
| Network name | Name assigned in `manifest.hocon` | Optional prefix followed by a UUID |
<!-- pyml enable line-length -->

## Registry files

In this mode, the producer writes an agent network HOCON file to a registry and
adds the network to `manifest.hocon`. The server's registry watcher detects the
file-system changes and reloads the permanent network storage.

Set `AGENT_MANIFEST_UPDATE_PERIOD_SECONDS` to a positive integer on every server
that must detect changes at runtime. The value is the number of seconds between
update cycles. It defaults to `0`, including in the supplied Dockerfile, which
disables runtime updates. A server with updates disabled still loads its manifest
at startup, so restarting it also makes the changed files available.

The watcher polls the registry directory every second when the update period is
five seconds or less. For longer update periods, it polls approximately four
times per update cycle. A detected change is applied on the next update cycle,
so consumers should not assume that a newly written network is immediately
available.

Use this mode when the generated network should have a stable name, be reviewed
or versioned as a file, or remain available across server restarts.

## In-memory reservations

In this mode, the producer reserves a temporary name and deploys the network
through the server's `Reservationist` interface. The name consists of an optional
producer-supplied prefix and a UUID. The server processes deployments through
asynchronous queues and stores them in its temporary network storage; it does not
write an agent HOCON file or change `manifest.hocon`.

The temporary-network updater starts independently of the registry watcher, so
`AGENT_MANIFEST_UPDATE_PERIOD_SECONDS` may remain `0`. Reservations expire after
their requested lifetime, capped by the server's maximum lifetime. The default
maximum is 24 hours.

By default, temporary networks exist only in server memory and are lost when that
server process restarts. Deployments that need shared or restart-tolerant
reservation storage can configure `AGENT_EXTERNAL_RESERVATIONS_STORAGE` with a
supported `ReservationsStorage` implementation and its provider-specific settings.
The example Dockerfile lists the available external-storage environment variables.

Use this mode for short-lived generated networks that should not modify a registry
or its manifest.

## Deprecated update setting

`AGENT_TEMPORARY_NETWORK_UPDATE_PERIOD_SECONDS` is deprecated and is not read by
the server. It belonged to an older periodic synchronization mechanism. Temporary
network deployments now use asynchronous queues, so remove this variable from
deployment configuration rather than relying on it to control reservation updates.

For the manifest format and permanent storage scopes, see the
[manifest HOCON reference](manifest_hocon_reference.md). For deployment environment
variables, see the comments near the end of the example
[Dockerfile](../neuro_san/deploy/Dockerfile).
