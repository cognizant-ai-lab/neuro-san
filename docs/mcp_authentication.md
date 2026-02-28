# MCP Authentication Guide

## Overview

Neuro-san supports machine-to-machine authentication for MCP servers that require credentials before granting access to tools.
This guide explains the available authentication methods and how to configure them.

---

## Authentication Methods

Neuro-san supports three authentication methods, applied in the following priority order:

1. **Headers** (highest priority)
   - Typically uses the `Authorization` field with `Bearer <token_value>`
   - Required fields depend on the authentication scheme expected by the MCP server

2. **Refresh Token** (fallback if headers unavailable or invalid)
   - Exchanges client ID and refresh token for an access token
   - Used when both client credentials and refresh token are available

3. **Client Credentials** (lowest priority)
   - Exchanges client ID and/or client secret for an access token
   - Used when only client information is provided

---

## Configuration Methods

Authentication data can be provided in two ways: through `sly_data` or via an environment variable configuration file.

### Method 1: Using `sly_data`

Pass authentication credentials directly in the `sly_data` object.
You can specify different credentials for different MCP URLs.

**Available Fields:**
- `http_headers` - HTTP headers for authentication
- `mcp_client_info` - Client credentials for token exchange
- `mcp_tokens` - Token information (only available via sly_data)

**Example:**

```hocon
{
    "http_headers": {
        "<MCP_URL_1>": {
            "Authorization": "Bearer <token_value>"
        }
    },
    "mcp_client_info": {
        "<MCP_URL_2>": {
            "client_id": "<client_id>",
            "client_secret": "<client_secret>",  # Optional if token_endpoint_auth_method is None
            "token_endpoint_auth_method": "client_secret_post",  # Optional, default: "client_secret_basic"
            "scope": "<scope>"  # Optional, default: None
        }
    },
    "mcp_tokens": {
        "<MCP_URL_3>": {
            "access_token": "<access_token>",
            "token_type": "<token_type>",
            "expires_in": <seconds>,
            "scope": "<scope>",
            "refresh_token": "<refresh_token>"
        }
    }
}
```

### Method 2: Using Configuration File

Set the `AGENT_MCP_INFO_FILE` environment variable to point to a HOCON configuration file.

**Important Notes:**
- `MCP_SERVERS_INFO_FILE` is deprecated and will be removed in version 0.7.0
- Server info (e.g., token endpoints) can only be configured via environment variable
- If not provided, server info from discovery will be used
- Server URLs must match those defined in the agent network HOCON file
- We strongly recommend **not** storing secrets directly in any source file.
Source files can easily be committed to version control, and checking in secrets is a serious security risk.
If these configuration files need to be committed, use **HOCON substitution** (e.g., environment variable references)
instead of hardcoding secret values.

**Example Configuration:**

```hocon
{
    "mcp_server_url_1": {
        "http_headers": {
            "Authorization": "Bearer <token>"
        },
        "mcp_client_info": {
            "client_id": "<client_id>",
            "client_secret": "<client_secret>",
            "token_endpoint_auth_method": "client_secret_post",
            "scope": "<scope>"
        },
        "mcp_server_info": {
            "token_endpoint": "https://example.com/token"  # Optional, default: discovery endpoint or base_url/token
        },
        "auth_timeout": 300.0,  # Optional timeout in seconds, default: 300.0
        "tools": ["tool_1", "tool_2"]  # Optional tool filtering
    }
}
```

**Alternative Environment Variables:**
- `AGENT_MCP_TIMEOUT_SECONDS` - Can be used instead of the `auth_timeout` field

---

## Configuration Precedence Rules

When authentication data exists in multiple locations, the following precedence applies:

1. **sly_data takes precedence** over configuration file for headers and client info on the same server
2. **Configuration file tool filtering** is used only if no tool filtering exists in the agent network HOCON file

---

## Field Reference

### `http_headers`

| Field | Description | Required |
|-------|-------------|----------|
| `Authorization` | Authentication header, typically `Bearer <token>` | Depends on server |

### `mcp_client_info`

| Field | Description | Required | Default |
|-------|-------------|----------|---------|
| `client_id` | OAuth client identifier | Yes | - |
| `client_secret` | OAuth client secret | Conditional* | - |
| `token_endpoint_auth_method` | Token exchange method | No | `client_secret_basic` |
| `scope` | Requested OAuth scopes | No | None |

*Required unless `token_endpoint_auth_method` is None

### `mcp_tokens`

| Field | Description | Required |
|-------|-------------|----------|
| `access_token` | Current access token | Yes |
| `token_type` | Token type (e.g., Bearer) | No |
| `expires_in` | Token expiration time in seconds | No |
| `scope` | Token scope | No |
| `refresh_token` | Token for refreshing access | No |

### `mcp_server_info`

| Field | Description | Required | Default |
|-------|-------------|----------|---------|
| `token_endpoint` | Custom token endpoint URL | No | Discovery endpoint or `base_url/token` |
