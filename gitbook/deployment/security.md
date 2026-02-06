# Security

Neuro SAN provides security features for shared and multi-user deployments.

## Multi-User Security Overlay

When deploying for multiple users, use a manifest overlay to disable agent networks that
have access to sensitive resources:

```bash
export AGENT_MANIFEST_FILE="registries/manifest.hocon registries/manifest_multiuser_overlay.hocon"
```

The overlay disables agents that can:

- Execute shell commands
- Access the filesystem
- Send emails from specific accounts
- Access external credentials

### Creating an Overlay

Create a manifest that sets dangerous agents to `false`:

```hocon
{
    "tools/code_executor.hocon": false,
    "tools/gmail_assistant.hocon": false,
    "experimental/file_manager.hocon": false
}
```

The overlay is applied after the base manifest, overriding any `true` values.

## API Key Security

### Never Hardcode Keys

Always use environment variables for API keys. Never put them in:

- HOCON configuration files
- Source code
- Docker images
- Git repositories

### Use Environment Variable Substitution

In HOCON files, reference environment variables:

```hocon
{
    "api_key": ${MY_API_KEY}
}
```

### Use Optional Substitution for Non-Critical Keys

```hocon
{
    "api_key": ${?OPTIONAL_API_KEY}
}
```

The `?` prefix means the substitution is optional and won't cause an error if the
variable is not set.

## sly\_data Access Control

Control which sly\_data keys agents can read and write using the `allow` block:

```hocon
{
    "name": "billing_agent",
    "allow": {
        "to_upstream.sly_data": ["invoice_id"],
        "to_downstream.sly_data": ["user_id"],
        "from_downstream.sly_data": ["payment_status"]
    }
}
```

This prevents agents from accessing data outside their authorized scope.

## Network Isolation

### Public vs. Private Agents

Control visibility in the manifest:

```hocon
{
    "internal_agent.hocon": {
        "serve": true,
        "public": false
    },
    "public_agent.hocon": {
        "serve": true,
        "public": true
    }
}
```

Private agents can only be called by other agents within the same network, not by
external clients.

## Next Steps

- [Configuration](configuration.md) -- Environment setup
- [Observability](observability.md) -- Monitoring and audit trails
