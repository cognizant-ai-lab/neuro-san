# External Agents

An agent's [`tools`](./agent_hocon_reference.md#tools-agents) list can name agent networks outside its own
network definition. Such an entry is an _external agent_: the calling agent sees it as one tool, and the
external network's front man answers the call. This allows common agent network definitions to be used as
functions for other networks, and enables entire ecosystems of agent webs.

To call tools on a Model Context Protocol server instead, see [MCP Servers as Tools](./mcp_tools.md).

<!--TOC-->

- [Same-server references](#same-server-references)
- [Remote server references](#remote-server-references)
    - [Ports](#ports)
    - [HTTPS requirement](#https-requirement)

<!--TOC-->

## Same-server references

It is possible for any agent to reference another agent on the same server by adding a forward-slash
in front of the served agent's name.  This is typically the stem of an agent network hocon file in
a deployment's registries directory.

Example: `/date_time` or `/math_guy`

## Remote server references

It is also possible to reference agents on other neuro-san _servers_ by using a URL as a tool reference.

Examples: `http://localhost:8080/math_guy` or `https://agents.example.com/deep/math_guy`

The path of the URL is the served agent's name. It may contain `/` when the remote server keeps its
registries in nested directories, as in `deep/math_guy` above.

### Ports

Which port is used depends on the kind of reference:

- An `https://` reference without an explicit port uses the well-known https port (443), on the assumption
  that a TLS-terminating proxy or load balancer sits in front of the remote neuro-san server.
- An `http://` reference without an explicit port uses the neuro-san server's default http port (8080).
- Exception for `localhost`: a `http://localhost/...` or `https://localhost/...` reference without an explicit
  port uses the referencing server's own configured port, the same as a `/name` reference, so the 443 default
  above does not apply to it.
- A same-server `/name` reference (see above) resolves on the server running the referencing network,
  so no host or port is involved.

### HTTPS requirement

When a server runs with `AGENT_SESSION_REQUIRE_HTTPS=true` (the default in the shipped Dockerfile), only `https://`
URL references to remote servers are accepted; a remote `http://` reference fails when the tool is called.
Same-server references are unaffected, because they are resolved in-process without an http session: that is
every `/name` reference, and an `http://localhost/...` reference to a network this same server serves.
