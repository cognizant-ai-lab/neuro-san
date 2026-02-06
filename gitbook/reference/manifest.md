# Manifest HOCON Reference

The manifest file registers which agent networks are available to the server. It maps
HOCON file paths to configuration values that control how each network is served.

## File Location

The default manifest is at `registries/manifest.hocon`. Override with:

```bash
export AGENT_MANIFEST_FILE="path/to/manifest.hocon"
```

Multiple manifest files can be layered (space-separated):

```bash
export AGENT_MANIFEST_FILE="registries/manifest.hocon registries/manifest_overlay.hocon"
```

Later files override earlier ones, which is useful for multi-user security overlays.

## Format

Each entry maps an agent network HOCON file path to either a boolean or a dictionary.

### Boolean Value

The simplest form. `true` enables the network, `false` disables it:

```hocon
{
    "hello_world.hocon": true,
    "disabled_agent.hocon": false
}
```

### Dictionary Value

Provides fine-grained control:

```hocon
{
    "hello_world.hocon": {
        "serve": true,
        "public": true,
        "mcp": true
    }
}
```

## Fields

| Field | Type | Default | Description |
|:------|:-----|:--------|:------------|
| `serve` | boolean | `true` | Whether the server loads this network |
| `public` | boolean | `false` | Whether the network is listed in public APIs |
| `mcp` | boolean | `false` | Whether the network is exposed as an MCP tool |

When using the boolean shorthand (`true`), it is equivalent to:

```hocon
{
    "serve": true,
    "public": false,
    "mcp": false
}
```

## Including Sub-Manifests

Use HOCON includes to organize manifests by category:

```hocon
{
    include "registries/basic/manifest.hocon"
    include "registries/tools/manifest.hocon"
    include "registries/industry/manifest.hocon"

    "my_custom_agent.hocon": true
}
```

Sub-manifests use the same format. File paths in sub-manifests are relative to the
registries directory.

## Multi-User Security Overlay

For shared deployments, create an overlay that disables agents with access to sensitive
resources:

```hocon
{
    "shell_executor.hocon": false,
    "file_manager.hocon": false,
    "gmail_assistant.hocon": false
}
```

Apply it by adding the overlay to the manifest file list:

```bash
export AGENT_MANIFEST_FILE="registries/manifest.hocon registries/manifest_multiuser_overlay.hocon"
```

## Hot Reload

The server monitors the manifest file for changes. When the file is modified, the server
reloads the agent registry without restarting. Control the polling interval:

```bash
python -m neuro_san.service.main_loop.server_main_loop \
    --manifest-update-period-seconds 60
```

Set to `0` to disable hot reload.
