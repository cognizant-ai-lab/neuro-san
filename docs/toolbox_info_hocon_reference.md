# Toolbox Info HOCON File Reference

This document describes the specifications for the toolbox info file used in the **neuro-san** system. This file
allows you to extend or override the default tools shipped with the neuro-san library.

The **neuro-san** system uses the HOCON (Human-Optimized Config Object Notation) format for data-driven configuration. HOCON
is similar to JSON but includes enhancements such as comments and more concise syntax. You can explore the full
[HOCON specification on GitHub](https://github.com/lightbend/config/blob/main/HOCON.md) for further details.

Specifications in this document are organized hierarchically, with header levels indicating the nesting depth of dictionary
keys. For dictionary-type values, their sub-keys will be described in the next heading level.

<!--TOC-->

- [Toolbox Info HOCON File Reference](#toolbox-info-hocon-file-reference)
    - [Toolbox Info Specifications](#toolbox-info-specifications)
    - [Tool Definition Schema](#tool-definition-schema)
        - [Langchain Tools](#langchain-tools)
            - [class](#class)
            - [args](#args-optional)
            - [base_tool_info_url](#base_tool_info_url-optional)
            - [display_as](#display_as-optional)
        - [Coded Tools](#coded-tools)
            - [class](#class-1)
            - [description](#description)
            - [parameters](#parameters-optional)
            - [display_as](#display_as-optional-1)
    - [Extending Toolbox Info](#extending-toolbox-info)
        - [AGENT_TOOLBOX_INFO_FILE environment variable](#agent_toolbox_info_file-environment-variable)
        - [toolbox_info_file key in specific agent hocon files](#agent_toolbox_info_file-and-toolbox_info_file-keys-in-agent-network-hocon)

<!--TOC-->

---

## Toolbox Info Specifications

The default configuration file used by the system is:
[toolbox_info.hocon](../neuro_san/internals/run_context/langchain/toolbox/toolbox_info.hocon).

This file defines all tools that the system can recognize and use at runtime. It supports two primary categories:

- **Langchain tools** – Based on LangChain's `BaseTool`, typically prebuilt utilities like search and HTTP tools.
- **Coded tools** – Custom Python tools implemented using the `CodedTool` interface.

The specific tools included by default may change over time. For the most up-to-date list, refer directly to the source file
above

The next section documents the schema and expected structure of each tool definition so you can define or override tools
in your own configuration files.

---

## Tool Definition Schema

Each top-level key in the toolbox info file represents a usable tool name. These names can be referenced in the
agent network’s [`toolbox`](./agent_hocon_reference.md#toolbox).

The value for each key is a dictionary describing the tool's properties. The schema differs slightly between
`langchain tools` and `coded tools`, as detailed below.

### Langchain Tools

These tools extend from the Langchain's `BaseTool` class.

#### `class`

Fully qualified class name of the tool. It must exist in the server's `PYTHONPATH`.

Example:

```hocon
"class": "langchain_community.tools.bing_search.BingSearchResults"
```

If the class is a Langchain **toolkit** (such as `RequestsToolkit`), it must implement a `get_tools()` method. When instantiated,
the toolkit returns a list of individual tools via this method — each of which will be available for the agent to call.

#### `args` *(optional)*

A dictionary of arguments for tool initialization.

If **omitted**, the tool class will be instantiated with its default constructor (i.e., no arguments).

Example:

```hocon
"args": {
        "max_results": 5
}
```

May include nested configurations.

Example:

```hocon
"args": {
    "api_wrapper": {
        "class": "langchain_community.utilities.BingSearchAPIWrapper",
        "args": {
            "k": 3
        }
    }
}
```

This instantiates `BingSearchResults(api_wrapper=BingSearchAPIWrapper(k=3))`

#### `base_tool_info_url` *(optional)*

Reference URL pointing to Langchain’s documentation for the specific tool.

This field is for user reference only—**it is not used by the system** during tool loading or execution.

#### `display_as` *(optional)*

Display type for clients. Options:

- `"coded_tool"`
- `"external_agent"`
- `"langchain_tool"` (default)
- `"llm_agent"`
  
  If **not provided**, the tool is inferred as `"langchain_tool"` unless it contains a [`description`](#description).

### Coded Tools

These tools extend from the `CodedTool` class.

#### [`class`](./agent_hocon_reference.md#class)

Fully qualified class name in the format `tool_module.ToolClass`. The `class` must point to a module available in your
`AGENT_TOOL_PATH` and server `PYTHONPATH`.

Example:

```hocon
"class": "web_search.WebSearch"
```

#### [`description`](./agent_hocon_reference.md#description)

A plain-language explanation of the tool’s behavior. This is essential for agents to understand how and when to use the tool.

#### [`parameters`](./agent_hocon_reference.md#parameters) *(optional)*

JSON schema-like structure describing the expected input arguments, types, and which are required.

If this field is **absent**, the LLM will simply call the tool **without providing any arguments**.

Example:

```hocon
"parameters": {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "The search query"
        }
    },
    "required": ["query"]
}
```

<!--- pyml disable-next-line no-duplicate-heading -->
#### `display_as` *(optional)*

Display type for clients. Options:

- `"coded_tool"` (default)
- `"external_agent"`
- `"langchain_tool"`
- `"llm_agent"`

If **omitted**, tools with a `description` are treated as `"coded_tool"`; otherwise, `"langchain_tool"`.

---

## Extending Toolbox Info

To customize the set of tools available to agents in the neuro-san system, you can provide your own toolbox info file.
This allows you to add, override, or refine tool definitions beyond what's included by default, and can be done in two ways:

### `AGENT_TOOLBOX_INFO_FILE` Environment Variable

You can configure a global toolbox info file for all agents by setting the `AGENT_TOOLBOX_INFO_FILE` environment variable:

```bash
export AGENT_TOOLBOX_INFO_FILE=/path/to/your/toolbox_info.hocon
```

This method is ideal for system-wide setups where multiple agents share the same toolset.
It lets you apply changes across the board without editing each agent configuration individually.

### `agent_toolbox_info_file` and `toolbox_info_file` Keys in Agent Network HOCON

If you need more flexibility, you can specify a custom toolbox file directly in an agent’s HOCON config
using one of the following keys:

- [`agent_toolbox_info_file`](./agent_hocon_reference.md#agent_toolbox_info_file) – preferred key

- [`toolbox_info_file`](./agent_hocon_reference.md#toolbox_info_file) – used as a fallback

These per-agent settings override any value set via the `AGENT_TOOLBOX_INFO_FILE` environment variable.
This is useful when individual agents require specialized or isolated tool configurations.
