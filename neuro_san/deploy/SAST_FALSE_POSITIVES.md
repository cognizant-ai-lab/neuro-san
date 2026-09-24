# SAST False Positives

Certain SAST reports (Static Application Security Testing) are generated with each release,
and each release has a continuing crop of what we consider to be false-positives in those reports.
This document is an attempt to explain the reasoning behind considering them false positives
and document steps you can take to further harden your system if you are concerned about them.

Note that within this document we do not mention the specific lines of code that are false positives,
nor do we mention the specific file in which they are contained because we reserve the right to
modify source during improvements and refactors more often that this file, however we expect the false
positive reports to linger.  Please refer to the SAST report itself for the release with which you are
concerned for the specific files and lines of code.  When examining those lines of code for yourself,
note that we tend to add a comment as to the nature of the false positive within the code itself
as well as this document.

## leaf-common package

### Improper Resource Shutdown or Release

Source Class: LocalFilePersistenceMechanism
Destination Class: Same

The complaint is that the fileobj object is not closed before returning from the function,
however this is precisely filling the contract required by AbstractPersistenceMechanism parent class
which requires an open file-like object returned from the open_source_for_read() method.

## neuro-san package

### Unchecked Input Loop Conditions

Source Classes:
    McpServiceAgentSession
    HttpConciergeSession

These are all cases where we are getting lists of external agents/tools from other servers.
By default to limit developer frustration, we allow any number of agents to be returned from any server.
In the vast majority of deployments, the agents from other servers and the references to the servers enabling
those agents are static and well-known to the deployers of neuro-san systems and are not abusers of these agent lists.
However, security considerations require us to allow deployments to be more careful when they need to be.

For production: set MAX_AGENTS_FROM_EXTERNAL_SERVER to an integer limit comfortable for your deployment.
    (the default is 0, which implies unlimited agents)


Source Class: OpenFgaAuthorizer
Destination Class: Same

We consider this to be a false positive for a couple of reasons:
1. Use of OpenFgaAuthorizer is completely optional and never a default.
2. Should OpenFgaAuthorizer be used at all, the OpenFGA server which is
   configured at deploy-time to be providing the response is assumed to be under complete
   control of those overseeing the deployment.
If developers are still concerned about this as a security risk, we welcome
propsed improvements via pull requests from an engaged community.

### Communication Over HTTP

Source Class: AbstractHttpServiceAgentSession
Destination Class: HttpServiceAgentSession and HttpConciergeSession

The string literal "http" is flagged as a medium-level "Communication over HTTP" issue.
The method in AbstractHttpServiceAgentSession only builds the URL and also is afforded https as an option.
The caller decides whether to use https by providing appropriate session/security configuration.
HTTP support is kept for ease of local development where certificates are often unavailable and
an extreme undue burden on development.

For production: set AGENT_SESSION_REQUIRE_HTTPS=true (and configure https) to forbid http.

### Information Exposure Through an Error Message / Filtering Sensitive Logs

Destionation Classes:
    LangChainOpenAIFunctionTool
    AwsSyncClientWorker
    AwsAsyncClientWorker
    HttpLlmTracer
    RegistryManifestRestorer
    ProfilerControlHandler
    HttpServer
    AuthorizerFactory

We employ a special SensitiveLogger class in all of these locations to optionally
forbid the logging of senstive information, such as exceptions or use of specific class names
in cases of dynamic resolution.  By default, the sensitive information is indeed logged
for developer convenience, as in all cases the need to impart whatever sensitive information
is to be logged is critical to the development cycle.

For production: set LEAF_LOG_SENSITIVE="true" to forbid such information leaking to the logs.
