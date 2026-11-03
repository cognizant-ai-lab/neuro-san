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
- [Agent network file references](#agent-network-file-references)
    - [Requirements for a fetched network](#requirements-for-a-fetched-network)

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

## Agent network file references

A tool reference can also be a URL or path to an agent network file, rather than to an agent that a server serves.
The file is fetched, checked and then run in-process, as if it were in the registries directory.

Examples: `https://example.com/nets/math_guy.hocon`, `file:///opt/nets/math_guy.hocon` or
`/opt/nets/math_guy.hocon`

- The path must end in `.hocon` or `.json`, which selects how the file is parsed. A `file://` URL that ends in
  anything else fails validation, and so does a bare path that is not a
  [same-server reference](#same-server-references).
- An `http://` or `https://` URL is downloaded. A `file://` URL or a bare path is read from the local filesystem of
  the process that runs the referencing network, which for a deployment is the server.
- A fetched network is cached by its URL, so the same reference is not fetched again on every call.
- Files are fetched only by in-process sessions, which a server always uses. When fetching fails, or the file
  does not pass the checks below, the reference is treated as a [remote server reference](#remote-server-references)
  instead, which normally leaves the tool out as unreachable.

See [math_guy_passthrough_to_network_file.hocon](../neuro_san/registries/math_guy_passthrough_to_network_file.hocon)
for an example that fetches
[math_guy_fully_qualified.hocon](../neuro_san/registries/math_guy_fully_qualified.hocon).

### Requirements for a fetched network

A fetched network goes through the same checks as a network in the registries directory, plus one more: every
CodedTool [`class`](./agent_hocon_reference.md#class-1) must be a fully-qualified reference to a module on the
server's `PYTHONPATH`, such as `neuro_san.coded_tools.math_guy.calculator.Calculator`. The short form that is
relative to `AGENT_TOOL_PATH` depends on the agent network name, and a URL does not map to a directory under
`AGENT_TOOL_PATH`.

Fully-qualified references do not resolve when `AGENT_TOOL_PATH_ONLY` is `true`, which the shipped
[Dockerfile](../neuro_san/deploy/Dockerfile) sets. On a server with that flag set, a fetched network that uses a
CodedTool still passes these checks, but fails when the CodedTool is called.

> [!IMPORTANT]
> Like a hocon file in the registries directory, a fetched agent network file is code-equivalent: it can name any
> class on the server's `PYTHONPATH` to load, and loading a class runs the top-level code of its module. Reference
> only files from sources you trust as much as your own registries.
