# Agent Manifest HOCON File Reference

This document describes the neuro-san specifications for the agent manifest .hocon file
used as configuration for neuro-san servers.  This file is useful for both agent developers
and devops/sysadmins who need to control just which/how agents are offered up to clients.

The neuro-san system uses the HOCON (Human-Optimized Config Object Notation) file format
for its data-driven configuration elements.  Very simply put, you can think of
.hocon files as JSON files that allow comments, but there is more to the hocon
format than that which you can explore on your own.

Specifications in this document each have header changes for the depth of scope of the dictionary
header they pertain to.
Some key descriptions refer to values that are dictionaries.
Sub-keys to those dictionaries will be described in the next-level down heading scope from their parent.

## Agent Manifest Specifications

All parameters listed here have global scope (to the agent network) and are listed at the top of the file by convention.

### File Name Keys

You will find that keys in the example [manifest.hocon](../neuro_san/registries/manifest.hocon)
are file references ending with the .hocon extension. Each of these *keys* points to a
[agent network hocon description](./agent_hocon_reference.md) file relative to the manifest.hocon's location.

### Values for File Name Keys

The value for any filename key is either a boolean value or a dictionary.

#### Boolean value

When the value is true, the agent described by the file key is served by the neuro-san server infrastructure
and listed in the Concierge Service which lists all the available agents on the server.

When the value is false, the agent described by the file key is neither served nor listed by the Concierge Service.

#### Dictionary value

The dictionary value in the manifest file allows for finer-grained control
over the serving and visibility of the agents with the following keys:

##### serve

The value for the "serve" key is a boolean.
This says whether or not the agent should be served up in any capacity.

Note that when this value is false (whether explicitly or implicitly),
the server will log a warning message on startup to inform you that the agent will not be served.
The idea is to have a run-time source of truth tostave off questions about "Why can't I see my agent X?".

##### public

The value for the "public" key is a boolean.
This says whether or not the agent should be listed in the Concierge service for discovery.

A true value implies that the network should be listed in the Concierge service as
part of a generic discovery process for clients.

Agents that have a false value for the "public" key are still callable by the outside world
and as external agents for other networks, but are not listed in the Concierge service at all.
This is useful for when your agent network is called as an external agent by another network,
but is considered an implementation detail for that network and is not intended for generic
discovery.

##### mcp

The value for the "mcp" key is a boolean.
This says whether or not the agent should be exposed through MCP protocol API
as an MCP tool. In this case, it will be listed by an MCP "tools/list" command.

A true value implies that the network will be available as an MCP tool.
Note that a true value specified for "mcp" key will implicitly set "public" key also to true.

## Server monitoring of agent description files

It is possible for the server infrastructure to detect changes to the agent manifest.hocon and any agent network
hocon files it refers to while the server is running.  When changes are detected, the server can add/remove entire
agents and/or uptake modifications in currently served agents.

This is useful in certain development situations,
and in certain dev-ops situations where mulitple neuro-san server pods share a common read-only volume mount of the
agent files as part of the cluster configuration.

By default, the environment variable AGENT_MANIFEST_UPDATE_PERIOD_SECONDS is set to 0, meaning this monitoring/update
feature is turned off.  When this value is > 0, it defines how often any server will scan for updates in the manifest.hocon
and other agent hocon files.

### More information

For more information on environment variables used in a neuro-san server deployment, see end of the example
[Dockerfile](../neuro_san/deploy/Dockerfile).
