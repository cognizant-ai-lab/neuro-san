# MCP Authentication Guide

Neuro-san supports machine-to-machine authentication for MCP servers that require credentials before granting
access to tools. This guide explains the available authentication methods and how to configure them.

<!--TOC-->

- [Authentication Methods](#authentication-methods)
- [Configuration Methods](#configuration-methods)
    - [Method 1: Using sly_data](#method-1-using-sly_data)
        - [http_headers](#http_headers)
            - [Authorization](#authorization)
        - [mcp_client_info](#mcp_client_info)
            - [client_id](#client_id)
            - [client_secret](#client_secret)
            - [token_endpoint_auth_method](#token_endpoint_auth_method)
            - [scope](#scope)
        - [mcp_tokens](#mcp_tokens)
            - [access_token](#access_token)
            - [refresh_token](#refresh_token)
    - [Method 2: Using Configuration File](#method-2-using-configuration-file)
        - [http_headers](#http_headers-1)
        - [mcp_client_info](#mcp_client_info-1)
        - [mcp_server_info](#mcp_server_info)
            - [token_endpoint](#token_endpoint)
        - [auth_timeout](#auth_timeout)
        - [tools](#tools)
- [Configuration Precedence Rules](#configuration-precedence-rules)

---

## Authentication Methods

Neuro-san supports three authentication methods, applied in the following priority order:

1. **Headers** (highest priority)
   - Typically uses the `Authorization` field with `Bearer <token_value>`
   - Required fields depend on the authentication scheme expected by the MCP server

2. **Refresh Token** (fallback if headers unavailable)
   - Exchanges client ID and refresh token for an access token
   - Used when both client credentials and refresh token are available

3. **Client Credentials** (lowest priority)
   - Exchanges client ID and/or client secret for an access token
   - Used when only client information is provided

---

## Configuration Methods

Authentication data can be provided in two ways: through `sly_data` or via an environment variable configuration file.

### Method 1: Using `sly_data`

Pass authentication credentials directly in the `sly_data` object. You can specify different credentials
for different MCP URLs.

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
            "client_secret": "<client_secret>",
            "token_endpoint_auth_method": "client_secret_post",
            "scope": "<scope>"
        }
    },
    "mcp_tokens": {
        "<MCP_URL_3>": {
            "access_token": "<access_token>",
            "refresh_token": "<refresh_token>"
        }
    }
}
```

#### `http_headers`

HTTP headers to be sent with requests to the MCP server for authentication purposes.

##### `Authorization`

The `Authorization` header field typically contains credentials for authenticating the client with the server.
The most common format is `Bearer <token_value>` for OAuth 2.0 bearer tokens,
but other authentication schemes may be used depending on the server's requirements
(e.g., `Basic`, `Digest`, or custom schemes).
Consult your MCP server's documentation for the specific authentication scheme required.

**Example:**

```hocon
"Authorization": "Bearer <token_value>"
```

#### `mcp_client_info`

Client credentials used for OAuth 2.0 authentication flows to obtain access tokens.

##### `client_id`

The OAuth 2.0 client identifier issued to the client during the registration process.
This is a required field that uniquely identifies your application to the authorization server.

**Example:**

```hocon
"client_id": "my-application-client-id"
```

##### `client_secret`

The OAuth 2.0 client secret issued to the client during registration.
This confidential credential is used to authenticate the client with the authorization server.
This field is required unless `token_endpoint_auth_method` is set to `null`.

**Example:**

```hocon
"client_secret": "super-secret-client-secret-value"
```

##### `token_endpoint_auth_method`

Specifies the authentication method used when exchanging credentials for
an access token at the token endpoint. This follows the OAuth 2.0 specification.

**Supported values:**
- `client_secret_basic` (default): Client credentials are sent via
HTTP Basic authentication, with the client ID and secret encoded in the `Authorization` header
- `client_secret_post`: Client credentials are sent in the request body as POST parameters
- `None`: No authentication (for public clients)

For more details on OAuth 2.0 client authentication methods,
see [RFC 6749 Section 2.3](https://datatracker.ietf.org/doc/html/rfc6749#section-2.3).

**Example:**

```hocon
"token_endpoint_auth_method": "client_secret_post"
```

##### `scope`

A space-separated list of OAuth 2.0 scopes being requested.
Scopes define the level of access that the application is requesting.
The available scopes depend on the MCP server's authorization server configuration.
If omitted, the server will use its default scopes.

**Example:**

```hocon
"scope": "read:data write:data admin:settings"
```

#### `mcp_tokens`

Token information for authentication. This field is only available when using `sly_data` configuration.

The system will attempt to authenticate using the provided `access_token`.
If authentication fails (e.g., due to token expiration), the system will automatically attempt to refresh
the access token using the `refresh_token` if one is provided.

**Note:** While standard OAuth 2.0 token responses include additional fields such as `token_type`, `expires_in`,
and `scope`, these fields are not used by the authentication system and should not be included in the configuration.

##### `access_token`

The OAuth 2.0 access token string used to authenticate requests to the MCP server. This is typically a JWT
(JSON Web Token) or an opaque token string issued by the authorization server.

**Example:**

```hocon
"access_token": "<token_value>"
```

##### `refresh_token`

An optional OAuth 2.0 refresh token that can be used to obtain a new access token when the current one expires or
fails. If provided, the system will automatically use this token to refresh authentication when needed.
Not all authorization servers issue refresh tokens, particularly for short-lived sessions or public clients.

**Example:**

```hocon
"refresh_token": "<refresh-token-string-value>"
```

### Method 2: Using Configuration File

Set the `AGENT_MCP_INFO_FILE` environment variable to point to a HOCON configuration file containing MCP authentication
settings. For detailed information about the structure and all available configuration options,
see the [MCP Info Configuration Documentation](mcp_info_hocon_reference.md).

**Important Notes:**
- `MCP_SERVERS_INFO_FILE` is deprecated and will be removed in version 0.7.0
- Server info (e.g., token endpoints) can only be configured via environment variable
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
            "token_endpoint": "https://example.com/token"
        },
        "auth_timeout": 300.0,
        "tools": ["tool_1", "tool_2"]
    }
}
```

<!--- pyml disable-next-line no-duplicate-heading -->
#### `http_headers`

Same as in Method 1. See the `http_headers` section under Method 1 for detailed field descriptions.

<!--- pyml disable-next-line no-duplicate-heading -->
#### `mcp_client_info`

Same as in Method 1. See the `mcp_client_info` section under Method 1 for detailed field descriptions.

#### `mcp_server_info`

Configuration for the MCP server's OAuth 2.0 endpoints and authentication behavior.

##### `token_endpoint`

The URL of the OAuth 2.0 token endpoint where the client exchanges credentials for access tokens.
If not provided, the system will attempt to discover the endpoint automatically through the server's
discovery mechanism, or fall back to `{base_url}/token`.

**Example:**

```hocon
"token_endpoint": "https://auth.example.com/oauth/token"
```

#### `auth_timeout`

The maximum time in seconds to wait for authentication operations to complete.
This includes token exchange requests and any other authentication-related network operations.
The default value is 300.0 seconds (5 minutes).

**Example:**

```hocon
"auth_timeout": 180.0  # 3 minutes
```

**Alternative:** You can also set the `AGENT_MCP_TIMEOUT_SECONDS` environment variable instead of using this field.

#### `tools`

An optional list of tool names to filter.
When specified, only the listed tools from this MCP server will be made available.
If omitted, all tools from the server are available.

**Example:**

```hocon
"tools": ["search_database", "update_record", "delete_record"]
```

---

## Configuration Precedence Rules

When authentication data exists in multiple locations, the following precedence applies:

1. **sly_data takes precedence** over configuration file for headers and client info on the same server
2. **Configuration file tool filtering** is used only if no tool filtering exists in the agent network HOCON file
