# Agent Network HOCON File Reference

This document describes the neuro-san specifications for a single agent network .hocon file
as used for each [registry](../neuro_san/registries)
in the [neuro-san](https://github.com/cognizant-ai-lab/neuro-san) and [neuro-san-studio](https://github.com/cognizant-ai-lab/neuro-san-studio)
repos.

The neuro-san system uses the HOCON (Human-Optimized Config Object Notation) file format
for its data-driven configuration elements.  Very simply put, you can think of
.hocon files as JSON files that allow comments, but there is more to the hocon
format than that which you can explore on your own.

Specifications in this document each have header changes for the depth of scope of the dictionary header they pertain to.
Some key descriptions refer to values that are dictionaries.
Sub-keys to those dictionaries will be described in the next-level down heading scope from their parent.

<!--TOC-->

- [Top-Level Agent Network Specifications](#top-level-agent-network-specifications)
    - [commondefs](#commondefs)
        - [replacement_strings](#replacement_strings)
        - [replacement_values](#replacement_values)
    - [agent_llm_info_file](#agent_llm_info_file)
    - [toolbox_info_file](#toolbox_info_file)
    - [llm_config](#llm_config)
        - [model_name](#model_name)
        - [temperature](#temperature)
        - [Other LLM-specific Parameters](#other-llm-specific-parameters)
        - [class](#class)
        - [fallbacks](#fallbacks)
    - [verbose](#verbose)
    - [max_iterations](#max_iterations)
    - [max_execution_seconds](#max_execution_seconds)
    - [error_formatter](#error_formatter)
    - [error_fragments](#error_fragments)
    - [tools](#tools)
- [Single Agent Specification](#single-agent-specification)
    - [name](#name)
    - [function](#function)
        - [description](#description)
        - [parameters](#parameters)
            - [type](#type)
            - [properties](#properties)
            - [required](#required)
        - [sly_data_schema](#sly_data_schema)
    - [instructions](#instructions)
    - [command](#command)
    - [tools (agents)](#tools-agents)
        - [External Agents](#external-agents)
    - [llm_config](#llm_config-1)
    - [class](#class-1)
    - [toolbox](#toolbox)
    - [args](#args)
    - [allow](#allow)
        - [connectivity](#connectivity)
        - [to_downstream](#to_downstream)
            - [sly_data](#sly_data)
        - [from_downstream](#from_downstream)
            - [sly_data](#sly_data-1)
        - [to_upstream](#to_upstream)
            - [sly_data](#sly_data-2)
    - [display_as](#display_as)
    - [max_message_history](#max_message_history)
    - [verbose](#verbose-1)
    - [max_iterations](#max_iterations-1)
    - [max_execution_seconds](#max_execution_seconds-1)
    - [error_formatter](#error_formatter-1)
    - [error_fragments](#error_fragments-1)
    - [structure_formats](#structure_formats)

<!--TOC-->

## Top-Level Agent Network Specifications

All parameters listed here have global scope (to the agent network) and are listed at the top of the file by convention.

### commondefs

A dictionary describing common definitions to be used throughout the particular agent network spec.

#### replacement_strings

A `commondefs` dictionary where keys are strings to be found within braces within strings
and the values of the dictionary are to replace those keys anywhere throughout the dictionary where string
values are to be found.  Example:

```json
{
    "commondefs": {
        "replacement_strings": {
            "operation": "addition",
            ...
        }
    }
    ...

        "instructions": "Perform the {operation} operation."
}
```

This results in a final interpretation where the `instructions` value is "Perform the addition operation."

Multiple passes are made for string replacements, so you can have string replacement values that also have
string replacement keys in them.

#### replacement_values

A `commondefs` dictionary where keys are strings to be found as full-values (no braces) and the values
of the dictionary are to replace those keys anywhere throughout the dictionary with the value defined
whenever an exact match of the string value is found.
values are to be found.  Example:

```json
{
    "commondefs": {
        "replacement_values": {
            "my_dict": {
                "key1": "my_value",
                "key2": 1.0
            }
            ...
        }
    }
    ...

        "function": "my_dict"
}
```

This results in a final interpretation where the `function` value is:

```json
"function": {
    "key1": "my_value",
    "key2": 1.0
}
```

Value replacement only happens once, but you can have replacement_strings references within
your string values within your replacement_values and things will work out as you might expect.

### agent_llm_info_file

The `agent_llm_info_file` key allows you to specify a custom HOCON file that extends the default list of available LLMs used
by agents in a neuro-san network. This is especially useful if you're using models that are not included in the default
configuration (e.g., newly released models or organization-specific endpoints).

For more information on selecting and customizing models, see the [model_name](#model_name) section below.

### toolbox_info_file

The `toolbox_info_file` key lets you define a custom HOCON file that adds to the default set of tools available to agents
within a neuro-san network. This is particularly helpful when you have tools shared across multiple agent networks.

For further details, refer to the [toolbox](#toolbox) section below.

### llm_config

An optional dictionary describing the default settings for agent LLMs when specifics
are not available for an given agent.  The default setting when this is not present
is to use an OpenAI gpt-4o model as the model_name for all agents.

#### model_name

The string model name to use for an agent in the network.
When this is not present, the default model is "gpt-4o" which is a decent all-purpose tool-using agent
which gets job done but doesn't cost a ton.

You can use any model listed in the [default_llm_info.hocon](../neuro_san/internals/run_context/langchain/llms/default_llm_info.hocon)
file included with the neuro-san distribution without any further modification.

While you can use any model you like for any agent within a neuro-san agent network,
you will need to use a model that has been specifically trained for "tool use" for any agent that
branches off work to any other agent/tool.  You can browse the `capabilities` section of the
`default_llm_info.hocon` to be sure the llm you choose can use tools.

Note that you will need your own access key set as an environment variable in order
to use LLMs from various providers.

| LLM Provider  | API Key environment variable  |
|:--------------|:------------------------------|
| Anthropic     | ANTHROPIC_API_KEY             |
| Azure OpenAI  | AZURE_OPENAI_API_KEY          |
| Google Gemini | GOOGLE_API_KEY                |
| NVidia        | NVIDIA_API_KEY                |
| Ollma         | &lt;None required&gt;         |
| OpenAI        | OPENAI_API_KEY                |

Note: _We strongly recommend to **not** set secrets as values within any source file._
These files tend to creep into source control repos, and it is **very** bad practice
to expose secrets by checking them in.

If your favorite model, or new hotness is not listed in `default_llm_info.hocon`,
you can still use it by specifying the [class](#class) key directly, or by extending the list in one of two ways:

(1) Set the absolute path to your extension HOCON file using the [agent_llm_info_file](#agent_llm_info_file)
key in the agent network HOCON file.

(2) Set the extension HOCON file to the environment variable
[AGENT_LLM_INFO_FILE](./llm_info_hocon_reference.md#AGENT_LLM_INFO_FILE-environment-variable).

For complete information on adding your own llm models or providers to the default llm info,
see the [llm_info_hocon_reference](./llm_info_hocon_reference.md).

#### temperature

Pretty much any of the LLMs will take a floating-point temperature parameter as an argument.
Roughly speaking, temperature is a number between 0.0 and 1.0 that indicates a relative amount of randomness
in answers provided by the LLM.  By default this value is 0.7.

#### Other LLM-specific Parameters

LLMs all come with various parameters like temperature that can be set on them.
As long as a parameter is a scalar listed in the args section for your LLM's class in the
[llm_info hocon file](../neuro_san/internals/run_context/langchain/llms/default_llm_info.hocon)
file, you can set that parameter in any llm_config within its own technical limits however you like.

Note: _We strongly recommend to **not** set secrets as values within any source file, including hocon files._
These files tend to creep into source control repos, and it is **very** bad practice
to expose secrets by checking them in.

#### class

You can use the `class` key in two ways:

#### 1. For supported providers (predefined in `default_llm_info.hocon`)

Set the `class` key to one of the values listed below, then specify the model using the `model_name` key.

| LLM Provider  | Class Value   |
|:--------------|:--------------|
| Anthropic     | anthropic     |
| Azure OpenAI  | azure_openai  |
| Google Gemini | gemini        |
| NVidia        | nvidiea       |
| Ollma         | ollama        |
| OpenAI        | openai        |

#### 2. For custom providers (not in `default_llm_info.hocon`)

Set the `class` key to the full Python path of the desired LangChain-compatible chat model class in the format:

```
<langchain_package>.<module>.<ChatModelClass>
```

Then, provide any constructor arguments supported by that class in `llm_config`.

For a full list of available chat model classes and their parameters, refer to:  
[LangChain Chat Integrations Documentation](https://python.langchain.com/docs/integrations/chat/)

> _Note: Neuro-SAN requires models that support **tool-calling** capabilities._

#### fallbacks

Fallbacks is a list of [llm_config](#llm_config) dictionaries to use in priority order.
When the an llm_config in the list fails for any reason, the next in the list is tried.

An simple example usage is given in [esp_decision_assistant.hocon](../neuro_san/registries/esp_decision_assistant.hocon).

You cannot have fallbacks listed within fallbacks.

### verbose

Controls server-side logging of agent chatter.

By default this is false, indicating no server-side logging is desired.
When true, basic langchain AgentExecutor verbosity is turned on for the agent.
There is an `extra` level of logging which enables a lanchain LoggingCallbackHandler for the agent.

Whenever any logging is turned on, it can be quite chatty, so this is not really a setting appropriate
for a production environment.  It's worth noting that most of the same information obtained by turning
on verbose can also be obtained by AGENT ChatMessages returned when the client's chat_filter is set to
MAXIMAL.

### max_iterations

An integer controlling the max_iterations of the langchain
[AgentExecutor](https://api.python.langchain.com/en/latest/agents/langchain.agents.agent.AgentExecutor.html)
used for the agent.  Default is 20.

We don't recommend deviating too far from the default of 20.
Some folks find it useful to _temporarily_ boost this waaaaay up when there is "network weather"
effecting your favorite LLM provider and you start to see "Agent stopped due to max iterations" errors.

### max_execution_seconds

An integer controlling the maximum amount of wall clock time (in seconds) to spend in the langchain
[AgentExecutor](https://api.python.langchain.com/en/latest/agents/langchain.agents.agent.AgentExecutor.html)
used for the agent.  Default is set for 2 minutes.

### error_formatter

String value which describes which error formatter to use by default for any agent in the network.

The default value is `string` which indicates that when errors occur, they are reported upstream
in their original string format.

An alternative value here is `json`, which formats the error output into a predictable json dictionary
which contains the following keys:

| Error Dictionary Key | Description |
|:---------------------|:------------|
| error     | The error message itself, usually from a Python exception |
| tool      | The name of the tool within the agent network that generated the error |
| details   | Optional string descibing details of the error. Could include a Traceback, for instance|

### error_fragments

A list of strings where if any one of the strings appears in agent output,
it is considered an error and reported as such per the [error_formatter](#error_formatter).

### tools

A list/array of [single agent specifications](#single-agent-specification) that make up the agent network.

The first of these in the list is called the "Front Man".
He handles all the dealings with any client of the agent network.

Other agents listed can be in any order and can reference each other, forming trees or graphs.

Typically any agent that is not the front-man is considered an implementation detail private
to the agent network definition. It is not possible to call these internal agents except from within
the agent network that defines them.  If you find your agent networks have some shared functionality
between them, consider elevating sub-networks to [external agent](#external-agents) status.

## Single Agent Specification

Settings for individual agents are specified by their own dictionary within the list of [tools](#tools) for the network.

There are a few settings that only apply to the front man.

### name

Every agent _must_ have a name.

Names can contain alphanumeric characters with "-" or "_" as word separators.
No spaces or other punctuation is allowed.
This allows for snake_case, camelCase, kebab-case, PascalCase, or SCREAMING_SNAKE_CASE
human-readable names, however you like them.

Any agent can refer to any other agent definition within the same agent network hocon file
by using its name in its [tools](#tools-agents) list.

### function

A dictionary which describes what an agent can do and how it wishes to be invoked for the
benefit of its upstream caller's planning.

Neuro-san largely follows the
[OpenAI function spec](https://platform.openai.com/docs/guides/function-calling?api-mode=responses#defining-functions),
however we do not require redefining the `name` (that is already given [above](#name))
and we also do not require redefining the `type` as this is always the same for every agent.

What is defined in this dictionary is what is returned for the agent's Function() neuro-san web API call.

#### description

Every agent _must_ have its function description filled out.
This is a single string value which informs anything upstream as to what _this_ agent can do for it.

For a user-facing front-man, what is contained in this description often suffices as a prompt for the user.

#### parameters

Parameters contains an optional [JSON Schema](https://json-schema.org) dictionary describing what
specific information the agent needs as input arguments when it is called.

A front-man typically does not need parameters defined, unless the agent network being described
is anticipated as being called from other agent networks.

##### type

The type of the parameters dictionary is always `object`.
This lets the parsing system know that the [properties](#properties) will be described as a dictionary.

##### properties

A dictionary whose keys each describe the name of a single argument to be used as input to an agent.
Each key's value is a dictionary describing the single argument value itself.
This dictionary has the following keys:

| Property Key | Description |
|:-------------|:------------|
| description  | A string which describes the particular argument |
| type         | A string describing the type of the property. (See below) |
| default      | An optional default value for the property |

Scalar types here can be "int", "float", "string", "bool".
It is possible that a properties' type can be "array"s for lists or "object"s for nested dictionaries.

Any sample agent hocon with more than one agent will have some example of a simple properties dictionary.
For a concrete, more complex properties definition, with nested objects and arrays,
See the definition of [cao_item in the esp_descision_assistant.hocon](../neuro_san/registries/esp_decision_assistant.hocon).

##### required

This is an optional list of string keys in the [properties](#properties) dictionary that are considered
to be required whenever an upstream agent calls the one being described.
Note that it's possible to specify a default value for any property that is not listed as required.

#### sly_data_schema

The optional [JSON Schema](https://json-schema.org) dictionary describing what
specific information the agent needs as input arguments over the private sly_data dictionary
channel when it is called.  The sly_data itself is generally considered to be private information
that does not belong in the chat stream, for example: credential information.

The sly_data_schema specification here has the same format as the [parameters](#parameters)
schema definition above.  Ideally there should be one [properties](#properties) entry per
sly_data dictionary input key, and any absolutely necessary keys should be listed in the [required](#required)
list.

Note that it is not strictly necessary to advertise to the outside world the sly_data_schema that
your agent network requires, but doing so does allow generic clients to prompt for this extra
information before sending any chat input.

The front-man is the only agent node that ever needs to specify this aspect of the [function](#function)
definition, as sly_data itself is already visible to all other internal agents of the network.

Example networks that advertise their sly_data_schema:

- [math_guy.hocon](../neuro_san/registries/math_guy.hocon)

### instructions

When included, the single (often very long) string value here tells an LLM-enabled agent
what it needs to do.

This is optional because not every tool listed in the agent network uses an LLM (there exist CodedTools).
But if you expect an agent to use an LLM, this instructions field is a must.

### command

An optional string to set an LLM-enabled agent in motion.

### tools (agents)

An optional list of strings with the names of other agents available for the agent being described to call.

Typically the names listed here are other agents within the same agent network definition,
often forming a tree structure, but overall agent networks are allowed to contain cycles.

It is important to note that just because an agent is listed in the tools does not mean that it will always
be called by an LLM.  The tools listing is merely a full description of what is _available_ to the agent.
It is the agent itself that actually decides which tools (if any) to invoke depending on its instructions
and the context of its query.

#### External Agents

This is not a hocon file key, but more a description of a concept that relates to listings of tools.

It is possible for any agent to reference another agent on the same server by adding a forward-slash
in front of the served agent's name.  This is typically the stem of an agent network hocon file in
a deployment's registries directory.

Example: `/website_search` or `/math_guy`

This allows common agent network definitions to be used as functions for other local networks.

Furthermore, it is also possible to reference agents on other neuro-san _servers_ by using a URL as a tool reference.

Example: `http://localhost:8080/math_guy`

This enables entire ecosystems of agent webs.

<!--- pyml disable-next-line no-duplicate-heading -->
### llm_config

It is possible for any LLM-enabled agent description to also have its own [llm_config](#llm_config)
dictionary.  This allows for agents to use the right agent for the job.
Some considerations might include:

- Use of lower-cost LLMs for lighter (perhaps non-tool-using) jobs
- Use of specially trained LLMs when subject matter expertise is required.
- Use of securely sequestered LLMs when sensitive information is appropos to a single agent's chat stream.

### class

Optional string specifying a Python class which implements the
[CodedTool](../neuro_san/interfaces/coded_tool.py)
interface.

<!-- pyml disable no-inline-html -->
Implementations must be found in the directory where the class can be resolved by looking
under the `AGENT_TOOL_PATH` environment variable setting as part of the `PYTHONPATH`.
By default neuro-san deployments assume that `PYTHONPATH` is set to contain the
top-level of your project's repo and that `AGENT_TOOL_PATH` is set to `<top-level>/coded_tools`.
In that directory each agent has its own folder and the value of the class is resolved
from there.
<!-- pyml enable no-inline-html -->

For example:
If the agent is called `math_guy` and the class is valued as `calculator.Calculator`,
The python file math_guy/calculator.py under `AGENT_TOOL_PATH` is expected to have
a class called Calculator which implements the CodedTool interface.

Implementations of the CodedTool interface must have implementations which:

- have a no-args constructor
- implement either the preferred `async_invoke()` or the discouraged synchronous `invoke()` method.

Agents representing CodedTools have the arguments described their [function parameters](#parameters)
populated by calling LLMs and passed in via the args dictionary of their async/invoke() method
when they are invoked.  They are also passed the sly_data dictionary which contains
private information not accessable to the chat stream.

Note that the CodedTool also has a synchronous invoke() method, but we discourage its use,
as neuro-san is expected to run in an asynchronous multi-threaded environment.
Using synchronous I/O calls within CodedTool implementations will result in loss of per-request
agent parallelism and performance problems at scale.

### toolbox

An optional string that refers to a predefined tool listed in a toolbox configuration file.
Currently supported tool types include:

- langchain's base tools
- coded tools.

The default toolbox configuration is located at [toolbox_info.hocon](../neuro_san/internals/run_context/langchain/toolbox/toolbox_info.hocon).

To use your own tools, create a custom toolbox `.hocon` file and reference it by either:

- Setting the `toolbox_info_file` key in the agent network `.hocon` file, or
- Defining the `AGENT_TOOLBOX_INFO_FILE` environment variable.

For more details on tool extension, see the [Toolbox Extension Guide](./toolbox_info_hocon_reference.md#extending-toolbox-info).

For more information on tool schema, see the [toolbox_info_hocon_reference](./toolbox_info_hocon_reference.md).

Example networks using tools from toolbox:

- [bing_search.hocon](../neuro_san/registries/bing_search.hocon)
which uses a langchain's base tool
- [website_rag.hocon](../neuro_san/registries/website_rag.hocon) which uses predefined
coded tools.

### args

Args is an optional dictionary for agents representing CodedTools to pass other
key/value pairs when the agent is invoked.  This allows for greater code sharing
for a single CodedTool implementation when it is referenced by multiple agents
and called in multiple contexts. It can also be used to supply or override arguments of Langchain tools defined in the [toolbox](#toolbox).

### allow

An optional dictionary which controls security policy pertaining to agent information flow.

#### connectivity

Boolean value which allows any agent within the network specification to control whether or
not to report any downstream tools during a Connectivity() API call, which allow for
pre-rendering of agent networks for demo/light-show purposes.

The default value of true says "sure, report all my downstream tools".
A false value does not allow such reporting.

Turning this value to false at the front-man prevents any connectivity reporting from happening.
Mid-level agents can have this be false to hide certain implementation details.

#### to_downstream

Dictionary which specifies security policy for information go _to_ downstream [external agents](#external-agents).
This has no effect on any information flowing between agents internal to the network.

##### sly_data

By default no sly_data goes out to any external agent.
To transmit sly_data to an external agent, you _must_ specificaly enable it.

A dictionary value whose keys represent keys in the sly_data dictionary.
Boolean values for each key tell whether or not that data is allowed to go through to external agents.
A string value in the dictionary represents a translation to a new key.

Example:

```json
    "allow": {
        "to_downstream": {
            "sly_data": {
                "user_id": true,
                "user_ssn": false,
                "my_session": "session_id"
            }
        }
    }
```

In simple sly_data situations you can simply specify which keys you want to allow
as a list:

```json
    "allow": {
        "to_downstream": {
            "sly_data": [ "user_id", "session_id" ]
        }
    }
```

#### from_downstream

Dictionary which specifies security policy for information coming _from_ downstream [external agents](#external-agents).
This has no effect on any information flowing between agents internal to the network.

<!--- pyml disable-next-line no-duplicate-heading -->
##### sly_data

By default no sly_data is accepted from any external agent.
To accept sly_data from an external agent, you _must_ specificaly enable it.

A dictionary value whose keys represent keys in the sly_data dictionary.
Boolean values for each key tell whether or not that data from any external agent
is allowed to be accepted and merged into this agent's sly_data.
A string value in the dictionary represents a translation to a new key.

The same dictionary/list specification described in [to_downstream](#sly_data) also applies here.

#### to_upstream

_Front Man only_
Dictionary which specifies security policy for information going back to any calling client.

This has no effect on any information flowing between agents internal to the network.

<!--- pyml disable-next-line no-duplicate-heading -->
##### sly_data

By default no sly_data goes back to the upstream caller from the agent network
To transmit sly_data to its upstream caller, you _must_ specificaly enable it.

A dictionary value whose keys represent keys in the sly_data dictionary.
Boolean values for each key tell whether or not that data internal to the agent network
is allowed to go back to the client in the final message.
A string value in the dictionary represents a translation to a new key.

The same dictionary/list specification described in [to_downstream](#sly_data) also applies here.

### display_as

An optional string that describes how the agent node wishes to appear to a client
that can visualize the network's connectivity.

When not present, the system determines the value given the configuration of the node
and will return one of the following strings:

- external_agent - for [External Agents](#external-agents)
- coded_tool - for a [CodedTool](../neuro_san/interfaces/coded_tool.py)
- langchain_tool - for a langchain tool
- llm_agent - for LLM-powered agents

### max_message_history

<!-- pyml disable-next-line no-emphasis-as-heading -->
_Front Man only_

An integer which tells the server how many of the most recent chat history messages
to send back in its chat_context field which allows for continuing a conversation
on the next client invocation.  By default this value is None, indicating there is no limit.

This is useful when end-user conversations with agents are expected to be lengthy and/or change
topics frequently.

<!--- pyml disable-next-line no-duplicate-heading -->
### verbose

Same as top-level [verbose](#verbose), except at single-agent scope.

<!--- pyml disable-next-line no-duplicate-heading -->
### max_iterations

Same as top-level [max_iterations](#max_iterations), except at single-agent scope.

<!--- pyml disable-next-line no-duplicate-heading -->
### max_execution_seconds

Same as top-level [max_execution_seconds](#max_execution_seconds), except at single-agent scope.

<!--- pyml disable-next-line no-duplicate-heading -->
### error_formatter

Same as top-level [error_formatter above](#error_formatter), except at single-agent scope.

<!--- pyml disable-next-line no-duplicate-heading -->
### error_fragments

Same as top-level [error_fragments above](#error_fragments), except at single-agent scope.

### structure_formats

<!-- pyml disable-next-line no-emphasis-as-heading -->
_Front Man only_

An optional list of strings describing the formats that the server-side should
parse into the structure field of the ChatMessage response so clients do not have
to re-invent this parsing wheel multiple times over.

The first single structure found of the appropriate format(s) from the text of a response
is what is put into the ChatMessage structure field, and any text which contributed to the
parsing of that structure is removed from the ChatMessage text field.

Supported values are:

- `json`    Looks for JSON in the messages from the LLM and extracts

Currently, the front-man is the only agent node that ever needs to specify this aspect of the [function](#function)
definition.

Example networks that parse their structure_formats:

- [music_nerd_pro.hocon](../neuro_san/registries/music_nerd_pro.hocon)
