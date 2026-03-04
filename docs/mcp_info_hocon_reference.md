# MCP Info Configuration Documentation

The MCP Info Configuration file is a HOCON-formatted file that contains authentication and connection settings for MCP
(Model Context Protocol) servers. This file is referenced by setting the `AGENT_MCP_INFO_FILE` environment variable
to point to its location.

The configuration file allows you to:

- Define authentication credentials for multiple MCP servers
- Configure OAuth 2.0 client credentials and token endpoints
- Set custom headers for authentication
- Specify timeouts for authentication operations
- Filter which tools from each server should be available

<!--TOC-->

- [Security Best Practices](#security-best-practices)
    - [Never Hardcode Secrets](#never-hardcode-secrets)
    - [Using HOCON Substitution](#using-hocon-substitution)
- [Configuration File Structure](#configuration-file-structure)
- [Configuration Fields](#configuration-fields)
    - [http_headers](#http_headers)
        - [Common Headers](#common-headers)
            - [Authorization](#authorization)
            - [X-API-Key](#x-api-key)
            - [Custom Headers](#custom-headers)
    - [mcp_client_info](#mcp_client_info)
        - [client_id](#client_id)
        - [client_secret](#client_secret)
        - [token_endpoint_auth_method](#token_endpoint_auth_method)
            - [client_secret_basic](#client_secret_basic)
            - [client_secret_post](#client_secret_post)
            - [null](#null)
        - [scope](#scope)
    - [mcp_server_info](#mcp_server_info)
        - [token_endpoint](#token_endpoint)
    - [auth_timeout](#auth_timeout)
    - [tools](#tools)
- [Complete Configuration Example](#complete-configuration-example)
- [Related Documentation](#related-documentation)

---

## Security Best Practices

### Never Hardcode Secrets

<!--- pyml disable-next-line no-emphasis-as-heading -->
**⚠️ CRITICAL SECURITY WARNING ⚠️**

We **strongly recommend NOT storing secrets directly in any source file**. This includes:
- API tokens and access tokens
- Client secrets
- Bearer tokens
- Passwords
- Any other sensitive credentials

**Why this matters:**
- Source files can easily be committed to version control systems (Git, SVN, etc.)
- Checking in secrets is a serious security risk that can lead to:
  - Unauthorized access to your systems
  - Data breaches
  - Compliance violations
  - Exposure of sensitive customer information

### Using HOCON Substitution

If your configuration files need to be committed to version control, **always use HOCON substitution** to reference
environment variables instead of hardcoding secret values.

**Secure approach using environment variable substitution:**

```hocon
{
    "https://api.example.com/mcp": {
        "http_headers": {
            "Authorization": "Bearer "${MCP_ACCESS_TOKEN}"
        },
        "mcp_client_info": {
            "client_id": "${MCP_CLIENT_ID}",
            "client_secret": "${MCP_CLIENT_SECRET}"
        }
    }
}
```

**Then set the environment variables separately:**

```bash
export MCP_ACCESS_TOKEN="your-actual-token-here"
export MCP_CLIENT_ID="your-client-id-here"
export MCP_CLIENT_SECRET="your-client-secret-here"
export AGENT_MCP_INFO_FILE="/path/to/mcp-config.hocon"
```

**Additional security recommendations:**
- Use a secrets management system (e.g., HashiCorp Vault, AWS Secrets Manager, Azure Key Vault)
- Rotate credentials regularly
- Use different credentials for different environments (dev, staging, production)
- Implement principle of least privilege - only grant necessary scopes
- Monitor and audit access to secrets

---

## Configuration File Structure

The configuration file is organized as a HOCON object where each key is an MCP server URL,
and the value is a configuration block for that server.

**Basic structure:**

```hocon
{
    "server_url_1": {
        # Configuration for server 1
    },
    "server_url_2": {
        # Configuration for server 2
    }
}
```

**Important notes:**
- Server URLs must be complete, valid URLs including the protocol (https://)
- Server URLs must exactly match those defined in your agent network HOCON file
- Each server can have its own independent authentication configuration
- Multiple authentication methods can be specified per server (with precedence rules applied)

---

## Configuration Fields

Each server URL maps to a configuration block that can contain the following top-level fields:

```hocon
{
    "https://api.example.com/mcp": {
        "http_headers": { ... },           # Optional: HTTP headers for authentication
        "mcp_client_info": { ... },        # Optional: OAuth 2.0 client credentials
        "mcp_server_info": { ... },        # Optional: Server endpoint configuration
        "auth_timeout": 300.0,             # Optional: Authentication timeout in seconds
        "tools": ["tool1", "tool2"]        # Optional: Tool filtering
    }
}
```

### `http_headers`

HTTP headers to be sent with requests to the MCP server for authentication purposes.
This is typically used for token-based authentication.

**Structure:**

```hocon
"http_headers": {
    "Header-Name-1": "header-value-1",
    "Header-Name-2": "header-value-2"
}
```

#### Common Headers

##### `Authorization`

The most commonly used authentication header. Supports various authentication schemes:

**Bearer Token Authentication (most common):**

```hocon
"http_headers": {
    "Authorization": "Bearer ${ACCESS_TOKEN}"
}
```

Bearer tokens are typically used with OAuth 2.0 and are defined in
[RFC 6750](https://datatracker.ietf.org/doc/html/rfc6750).
The token should be sent exactly as received from the authorization server.

**Basic Authentication:**

```hocon
"http_headers": {
    "Authorization": "Basic ${BASE64_CREDENTIALS}"
}
```

Where `BASE64_CREDENTIALS` is the base64 encoding of `username:password`.
See [RFC 7617](https://datatracker.ietf.org/doc/html/rfc7617).

**API Key Authentication:**

```hocon
"http_headers": {
    "Authorization": "ApiKey ${API_KEY}"
}
```

Some services use custom authentication schemes. Always refer to your MCP server's documentation.

##### `X-API-Key`

Some services use a custom header for API keys:

```hocon
"http_headers": {
    "X-API-Key": "${API_KEY}"
}
```

##### Custom Headers

You can include any custom headers required by your MCP server:

```hocon
"http_headers": {
    "X-Client-Id": "${CLIENT_ID}",
    "X-Request-ID": "unique-request-identifier",
    "X-Tenant-ID": "tenant-123"
}
```

**Complete example:**

```hocon
{
    "https://api.example.com/mcp": {
        "http_headers": {
            "Authorization": "Bearer ${MCP_TOKEN}",
            "X-API-Version": "2024-01",
            "X-Client-ID": "${CLIENT_ID}"
        }
    }
}
```

### `mcp_client_info`

OAuth 2.0 client credentials used for token-based authentication flows.
This section is used when you need to exchange client credentials for an access token.

**Structure:**

```hocon
"mcp_client_info": {
    "client_id": "string",
    "client_secret": "string",
    "token_endpoint_auth_method": "string",
    "scope": "string"
}
```

#### `client_id`

**Type:** String (required)

The OAuth 2.0 client identifier issued to your application during the registration process with the authorization
server. This uniquely identifies your application.

**Example:**

```hocon
"client_id": "${MCP_CLIENT_ID}"
```

**Best practices:**
- Always use environment variable substitution
- Client IDs are typically safe to commit to source control (they're not secret),
but using environment variables provides flexibility
- Keep a record of which client ID corresponds to which environment

#### `client_secret`

**Type:** String (conditionally required)

The OAuth 2.0 client secret issued to your application during registration.
This is a confidential credential that must be protected.

**Required when:**
- `token_endpoint_auth_method` is `client_secret_basic` or `client_secret_post`

**Not required when:**
- `token_endpoint_auth_method` is `null` (public clients)
- Using other authentication methods that don't require a client secret

**Example:**

```hocon
"client_secret": "${MCP_CLIENT_SECRET}"
```

**Security considerations:**
- **NEVER** hardcode client secrets in configuration files
- **ALWAYS** use environment variable substitution
- Treat client secrets with the same security level as passwords
- Rotate client secrets regularly
- Use different client secrets for different environments

#### `token_endpoint_auth_method`

**Type:** String (optional)  
**Default:** `client_secret_basic`

Specifies how the client authenticates with the authorization server's token endpoint.
This follows the OAuth 2.0 specification defined in
[RFC 6749 Section 2.3](https://datatracker.ietf.org/doc/html/rfc6749#section-2.3).

**Supported values:**

##### `client_secret_basic`

**Default method.** Client credentials are sent via HTTP Basic authentication.
The client ID and secret are combined as `client_id:client_secret`, base64-encoded,
and sent in the `Authorization` header.

```hocon
"token_endpoint_auth_method": "client_secret_basic"
```

**When to use:**
- Most common and widely supported method
- Recommended for server-to-server communication
- Credentials are not exposed in request body or logs

**Token request format:**

```http
POST /token HTTP/1.1
Host: auth.example.com
Authorization: Basic Base64(client_id:client_secret)
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials&scope=read write
```

##### `client_secret_post`

Client credentials are sent as POST parameters in the request body.

```hocon
"token_endpoint_auth_method": "client_secret_post"
```

**When to use:**
- When the authorization server doesn't support Basic authentication
- Required by some OAuth providers
- Less secure than `client_secret_basic` as credentials appear in request body

**Token request format:**

```http
POST /token HTTP/1.1
Host: auth.example.com
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials&client_id=xxx&client_secret=yyy&scope=read write
```

##### `null`

No client authentication is performed. Used for public clients that don't have a client secret.

```hocon
"token_endpoint_auth_method": null
```

**When to use:**
- Authorization servers that don't require client authentication

**Token request format:**

```http
POST /token HTTP/1.1
Host: auth.example.com
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials&client_id=xxx&scope=read write
```

#### `scope`

**Type:** String (optional)  
**Default:** None (server uses its default scopes)

A space-separated list of OAuth 2.0 scopes being requested.
Scopes define the specific permissions your application is requesting.
The available scopes are defined by the authorization server and vary by service.

**Example:**

```hocon
"scope": "read:data write:data admin:users"
```

**Understanding scopes:**
- Scopes represent permissions or access levels
- Request only the scopes your application needs (principle of least privilege)
- The authorization server may grant fewer scopes than requested
- Multiple scopes are separated by spaces (not commas)

**Common scope patterns:**

**Resource-based scopes:**

```hocon
"scope": "read:projects write:projects delete:projects"
```

**Action-based scopes:**

```hocon
"scope": "projects.read projects.write projects.delete"
```

**Role-based scopes:**

```hocon
"scope": "user admin superadmin"
```

### `mcp_server_info`

Configuration for the MCP server's OAuth 2.0 endpoints and authentication behavior.
This section provides additional server-specific settings that complement the client credentials.

**Structure:**

```hocon
"mcp_server_info": {
    "token_endpoint": "string"
}
```

#### `token_endpoint`

**Type:** String (optional)  
**Default:** Auto-discovered or `{base_url}/token`

The URL of the OAuth 2.0 token endpoint where the client exchanges credentials for access tokens.
This is where token requests are sent during authentication.

**When to specify:**
- The authorization server's token endpoint is different from the standard location
- The server doesn't support endpoint discovery
- You want to explicitly control which endpoint is used

**When to omit:**
- The server supports OAuth 2.0 discovery
- The token endpoint follows the standard pattern (`{base_url}/token`)

**Example:**

```hocon
"mcp_server_info": {
    "token_endpoint": "https://auth.example.com/oauth/token"
}
```

**Discovery mechanism:**

If `token_endpoint` is not provided,
the system attempts to discover it using the OAuth 2.0 Authorization Server Metadata discovery mechanism.

**Discovery order:**

The system follows the
[MCP 2025-11-25 specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/authorization)
and [RFC 8414](https://www.rfc-editor.org/rfc/rfc8414.html) for endpoint discovery:

1. **If no authorization server URL is specified in the MCP server's metadata:**
   - Checks `{server_netloc}/.well-known/oauth-authorization-server`
   - This is the legacy path defined in the MCP specification

2. **If an authorization server URL is found in the MCP server's metadata:**

   **For authorization servers with a path component** (e.g., `https://auth.example.com/tenant1`):
   - **Path-aware OAuth discovery ([RFC 8414 Section 3](https://www.rfc-editor.org/rfc/rfc8414.html#section-3)):**
     Checks `{base_url}/.well-known/oauth-authorization-server{path}`
     Example: `https://auth.example.com/.well-known/oauth-authorization-server/tenant1`

   - **Path-aware OIDC discovery ([RFC 8414 Section 5](https://www.rfc-editor.org/rfc/rfc8414.html#section-5)):**
     Checks `{base_url}/.well-known/openid-configuration{path}`
     Example: `https://auth.example.com/.well-known/openid-configuration/tenant1`

   - **OIDC 1.0 discovery
   ([OpenID Connect Discovery 1.0](https://openid.net/specs/openid-connect-discovery-1_0.html)):**
     Checks `{base_url}{path}/.well-known/openid-configuration`
     Example: `https://auth.example.com/tenant1/.well-known/openid-configuration`

   **For authorization servers without a path component** (e.g., `https://auth.example.com`):
   - **OAuth root discovery ([RFC 8414](https://www.rfc-editor.org/rfc/rfc8414.html)):**
     Checks `{base_url}/.well-known/oauth-authorization-server`
     Example: `https://auth.example.com/.well-known/oauth-authorization-server`

   - **OIDC 1.0 fallback
   ([OpenID Connect Discovery 1.0](https://openid.net/specs/openid-connect-discovery-1_0.html)):**
     Checks `{base_url}/.well-known/openid-configuration`
     Example: `https://auth.example.com/.well-known/openid-configuration`

**Token endpoint extraction:**

Once a valid OAuth Authorization Server Metadata document is discovered:
- If the metadata contains a `token_endpoint` field, that URL is used
- If the metadata is found but doesn't contain a `token_endpoint` field,
the system falls back to `{auth_base_url}/token`

**If all discovery attempts fail:**
- The system falls back to `{auth_base_url}/token`
- If this also fails, you must manually specify the `token_endpoint` in the `mcp_server_info` configuration

**Note:** The discovery URLs are tried in the order listed above.
The first successful response will be used to extract the token endpoint.

**Common endpoint patterns:**

```hocon
# Standard OAuth 2.0 pattern
"token_endpoint": "https://auth.example.com/oauth/token"

# Auth0 pattern
"token_endpoint": "https://tenant.auth0.com/oauth/token"

# Okta pattern
"token_endpoint": "https://tenant.okta.com/oauth2/default/v1/token"

# Custom authorization server
"token_endpoint": "https://auth.mycompany.com/v1/token"
```

### `auth_timeout`

**Type:** Float (optional)  
**Default:** 300.0 (5 minutes)  
**Unit:** Seconds

The maximum time to wait for authentication operations to complete. This includes:
- Token exchange requests
- Token refresh operations
- Any other authentication-related network operations
- Authorization server response time

**Example:**

```hocon
"auth_timeout": 180.0  # 3 minutes
```

**Choosing the right timeout:**

**Short timeouts (30-60 seconds):**
- Fast, reliable networks
- High-performance authorization servers
- Synchronous workflows where quick failures are preferred

**Medium timeouts (120-300 seconds):**
- Standard network conditions
- Most production environments
- Balance between responsiveness and reliability

**Long timeouts (300+ seconds):**
- Unreliable networks
- Slow authorization servers
- Asynchronous workflows where retries are expensive

**Example configurations:**

```hocon
# Development environment - fail fast
"auth_timeout": 30.0

# Production environment - standard timeout
"auth_timeout": 300.0

# Unstable network - generous timeout
"auth_timeout": 600.0
```

**Alternative configuration:**

Instead of using the `auth_timeout` field, you can set the `AGENT_MCP_TIMEOUT_SECONDS` environment variable:

```bash
export AGENT_MCP_TIMEOUT_SECONDS=180
```

**Precedence:** The `auth_timeout` field in the configuration file takes precedence over
the environment variable if both are set.

### `tools`

**Type:** Array of strings (optional)  
**Default:** None (all tools are available)

An optional list of tool names to filter from the MCP server.
When specified, only the listed tools will be made available to the agent. This is useful for:
- Limiting the agent's capabilities for security reasons
- Reducing complexity by exposing only necessary tools
- Creating specialized agents with focused functionality
- Testing specific tools in isolation

**Example:**

```hocon
"tools": ["search_database", "update_record", "delete_record", "create_report"]
```

**Filtering behavior:**

**If `tools` is specified:**
- Only tools in the list are made available
- Tools not in the list are hidden from the agent
- Invalid tool names are silently ignored
- Order doesn't matter

**If `tools` is omitted or empty:**
- All tools from the server are available
- No filtering is applied

**Tool filtering precedence:**

Tool filtering can be specified in two places:
1. Agent network HOCON file (higher precedence)
2. MCP info configuration file (lower precedence)

The configuration file's tool filtering is **only used if no tool filtering exists in the agent network HOCON file**.

**Use cases:**

**Security-focused filtering:**

```hocon
# Only allow read operations
"tools": ["read_data", "search_data", "list_data"]
```

**Environment-specific filtering:**

```hocon
# Development: all tools available
"tools": []

# Production: restricted to safe operations
"tools": ["read_data", "search_data", "generate_report"]
```

**Role-based filtering:**

```hocon
# Admin role
"tools": ["create", "read", "update", "delete", "admin_panel"]

# User role
"tools": ["read", "search"]
```

**Finding available tools:**

To discover which tools are available from an MCP server:
1. Check the server's documentation
2. Query the server's tool catalog endpoint (if available)
3. Temporarily omit the `tools` filter and observe which tools are registered

## Complete Configuration Example

```hocon
{
    # Server 1: Bearer token authentication
    "https://api.service1.com/mcp": {
        "http_headers": {
            "Authorization": "Bearer ${SERVICE1_TOKEN}",
        },
        "auth_timeout": 60.0,
        "tools": ["search", "list"]
    },

    # Server 2: Client credentials with custom token endpoint
    "https://api.service2.com/mcp": {
        "mcp_client_info": {
            "client_id": "${SERVICE2_CLIENT_ID}",
            "client_secret": "${SERVICE2_CLIENT_SECRET}",
            "token_endpoint_auth_method": "client_secret_post",
            "scope": "full_access"
        },
        "mcp_server_info": {
            "token_endpoint": "https://auth.service2.com/token"
        },
        "auth_timeout": 180.0
    },

    # Server 3: API key authentication
    "https://api.service3.com/mcp": {
        "http_headers": {
            "X-API-Key": "${SERVICE3_API_KEY}",
            "X-Client-ID": "my-app-123"
        },
        "tools": ["query", "update", "delete"]
    },

    # Server 4: Public client (no secret)
    "https://api.service4.com/mcp": {
        "mcp_client_info": {
            "client_id": "${SERVICE4_CLIENT_ID}",
            "token_endpoint_auth_method": "None"
        },
        "auth_timeout": 120.0
    }
}
```

## Related Documentation

- [MCP Specification Guide](https://modelcontextprotocol.io/specification/2025-11-25/basic)
- OAuth 2.0 Specifications:
  - [RFC 6749: OAuth 2.0 Authorization Framework](https://datatracker.ietf.org/doc/html/rfc6749)
  - [RFC 6750: Bearer Token Usage](https://datatracker.ietf.org/doc/html/rfc6750)
  - [RFC 7617: HTTP Basic Authentication](https://datatracker.ietf.org/doc/html/rfc7617)
