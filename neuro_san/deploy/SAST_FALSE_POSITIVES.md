# SAST False Positives

Certain SAST reports (Static Application Security Testing) are generated with each release,
and each release has a continuing crop of what we consider to be false-positives in those reports.
This document is an attempt to explain the reasoning behind considering them false positives
and document steps you can take to further harden your system if you are concerned about them.

Note that within this document we do not mention the specific lines of code that are false positives,
nor do we mention the specific file in which they are contained because we reserve the right to
modify source during improvements and refactors more often than this file, however we expect the false
positive reports to linger.  Please refer to the SAST report itself for the release with which you are
concerned for the specific files and lines of code; it is attached to each GitHub release as
`checkmarx-report.pdf`.  When examining those lines of code for yourself,
note that we tend to add a comment as to the nature of the false positive within the code itself
as well as this document.

## A note on defaults

Several sections below end with a "For production" setting.  Each of those environment variables
has two defaults to keep in mind:

* The default the library code uses when the variable is not set at all (leaf-common's, in the
  case of `LEAF_LOG_SENSITIVE`).  These lean towards developer convenience.
* The default baked into the Dockerfiles under `neuro_san/deploy`.  These lean towards production,
  so a container built from them already has the "For production" value unless something overrides it.

One thing that does override them is `neuro_san/deploy/run.sh`, the script for running that container
on a developer's machine: it deliberately passes `AGENT_SESSION_REQUIRE_HTTPS=false` and
`LEAF_LOG_SENSITIVE=true`.  Do not reuse it as-is for a production deployment.

## leaf-common package

### Improper Resource Shutdown or Release

* Source Class: LocalFilePersistenceMechanism
* Destination Class: Same

The complaint is that the fileobj object is not closed before returning from the function,
however this is precisely filling the contract of the PersistenceMechanism interface, inherited
through the AbstractPersistenceMechanism parent class, which allows an open file-like object
to be returned from the open_source_for_read() method.
The caller always does the closing, so this is not a security issue or resource leak.

## neuro-san package

### Unchecked Input Loop Conditions

* Source Class: McpServiceAgentSession, Destination Class: Same
* Source Class: HttpConciergeSession, Destination Class: AgentCli

These are cases where neuro-san *client* code -- in practice the `agent_cli` command-line tool --
asks the server it has been pointed at for the list of agents or tools that server serves, and then
loops over that list.  The complaint is that nothing bounds the length of the list the server sends back.

Neither class is used by the neuro-san server, so these two reports do not describe a way to attack a
deployed server.  (The server does fetch tool listings from MCP servers that an agent network names
among its tools, through LangChainMcpAdapter.  That is a different path, not flagged by these reports
and not bounded by this variable.)

By default, to limit developer frustration, the client considers however many agents or tools a server
lists.  If you run `agent_cli` against a server you do not control, you can bound that with
`MAX_AGENTS_FROM_EXTERNAL_SERVER` in the client's environment:

* A positive integer limits the listing to that many entries.  The client logs a warning whenever the
  limit truncates a listing.  `agent_cli --list`, `--tags` and `--tag` then simply show a shorter
  listing; `agent_cli --mcp` cannot find an agent listed beyond the limit and reports it as
  "not implemented on the server".
* Unset, empty, 0 (the default) and negative values mean no limit.
* Anything that is not an integer is ignored with a warning, so a typo does not silently pass for a limit.

The Dockerfiles set this variable to its default of 0 so that it is documented next to the other
settings.  The server never reads it, but `agent_cli` run inside the container does.

Note that the bound cleared the McpServiceAgentSession entry from the report, but the same bound in
HttpConciergeSession has not stopped the scanner from reporting the HttpConciergeSession / AgentCli
pair, so expect that entry to linger.  We consider it a false positive for the reasons above.

* Source Class: OpenFgaAuthorizer
* Destination Class: Same

We consider this to be a false positive for a couple of reasons:

1. Use of OpenFgaAuthorizer is completely optional and never a default.
2. Should OpenFgaAuthorizer be used at all, the OpenFGA server which is
   configured at deploy-time to be providing the response is assumed to be under complete
   control of those overseeing the deployment.

If developers are still concerned about this as a security risk, we welcome
proposed improvements via pull requests from an engaged community.

### Communication Over HTTP

* Source Class: AbstractHttpServiceAgentSession
* Destination Classes: HttpServiceAgentSession and HttpConciergeSession

The string literal "http" is flagged as a medium-level "Communication over HTTP" issue.
The method in AbstractHttpServiceAgentSession only builds the URL and also is afforded https as an option.
The caller decides whether to use https by providing appropriate session/security configuration.
HTTP support is kept for ease of local development where certificates are often unavailable and
an extreme undue burden on development.

For production: set `AGENT_SESSION_REQUIRE_HTTPS=true` (and configure https) to forbid http.
The library default is `false`; the Dockerfiles already set `true`.

### Information Exposure Through an Error Message / Filtering Sensitive Logs

Destination Classes:

* LangChainOpenAIFunctionTool
* AwsSyncClientWorker
* AwsAsyncClientWorker
* HttpxLlmTracer
* RegistryManifestRestorer
* ProfilerControlHandler
* HttpLogger (reached from HttpServer, which the report names as the source)
* AuthorizerFactory

We employ a special SensitiveLogger class in all of these locations to optionally
forbid the logging of sensitive information, such as exceptions or use of specific class names
in cases of dynamic resolution.  When forbidden, the whole log line is dropped rather than redacted.
By default the library does log this information for developer convenience, as in all cases the
need to impart whatever sensitive information is to be logged is critical to the development cycle.

For production: set `LEAF_LOG_SENSITIVE=false` to keep such information out of the logs.
The library default is `true` (log it); the Dockerfiles already set `false`.
