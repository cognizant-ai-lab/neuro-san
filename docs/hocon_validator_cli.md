# hocon_validation_cli

The hocon_validation_cli is a command-line tool for validating HOCON agent network configuration files.
The hocon_validation_cli is intended to be used in case your hocon file is not working as expected.
For instance, it isn't showing up in the neuro-san-studio's IDE in the browser.

This script validates HOCON files against neuro-san's agent network validation rules,
checking for issues such as:

- Missing or unreachable agents
- Invalid tool names
- Empty instructions
- Invalid URL references
- Malformed function.parameters blocks (nested keys, bad required refs, unrecognized types)

It also runs a set of best-effort lint checks and prints anything they find as warnings
(see [Lint Warnings](#lint-warnings) below): they don't fail validation unless you pass `--strict`.

For editor autocomplete/linting rather than a CLI run, see the
[agent network JSON Schema](./agent_hocon_schema.md).

Usage:

```sh
python -m neuro_san.client.hocon_validator_cli path/to/agent.hocon
python -m neuro_san.client.hocon_validator_cli path/to/agent.hocon --verbose
python -m neuro_san.client.hocon_validator_cli path/to/agent.hocon --registry-dir /path/to/registry
```

## Registry Directory Behavior

The validator uses a **registry directory** to resolve HOCON `include` statements.
This is important when your HOCON files contain includes like `include "registries/llm_info.hocon"`.

### Default Registry Directory

By default, the registry directory is determined as follows:

1. If the `AGENT_MANIFEST_FILE` environment variable is set, the registry directory is the parent directory of
   that file's parent directory (e.g., if `AGENT_MANIFEST_FILE=/path/to/neuro_san/registries/manifest.hocon`,
   then the registry directory is `/path/to/neuro_san`)
2. If `AGENT_MANIFEST_FILE` is not set, the registry directory defaults to the current working directory

### Overriding the Registry Directory

You can override the default registry directory using the `--registry-dir` option:

```sh
python -m neuro_san.client.hocon_validator_cli path/to/agent.hocon --registry-dir /path/to/your/project
```

This is useful when:
- Your HOCON file is outside your main project directory
- You want to validate against a different set of registry files
- Your includes reference a specific directory structure

### How It Works

When a registry directory is specified (either by default or via `--registry-dir`):

1. The validator temporarily copies your HOCON file to the registry directory
2. It parses the file from that location, allowing includes to be resolved correctly
3. After validation completes, the temporary file is automatically removed

## Examples

Validate any arbitrary hocon file:

```sh
python -m neuro_san.client.hocon_validator_cli path/to/agent.hocon
```

Validate a hocon in the `neuro-san-studio` directory:

```sh
python -m neuro_san.client.hocon_validator_cli registries/agent.hocon
```

Validate with verbose output:

```sh
python -m neuro_san.client.hocon_validator_cli registries/agent.hocon --verbose
```

Validate with a specific registry directory:

```sh
python -m neuro_san.client.hocon_validator_cli /tmp/my_agent.hocon --registry-dir /path/to/registry
```

## HOCONs with external agents

In case your hocon includes external agents using e.g. "/some_external_agent", your validation will fail unless
they are explicitly mentioned using the `--external-agents` argument.

For example (assuming that you are within the neuro-san-studio root directory)

```sh
python -m neuro_san.client.hocon_validator_cli registries/agent_network_architect.hocon --external-agents '/agent_network_designer' --verbose
```

You should see something like this:

```text
Validation passed: No errors found.

--- Agent Network Summary ---
Total agents/tools defined: 4

Agents:
  - Agent_Network_Architect (LLM Agent)
      Sub-tools: /agent_network_designer, agent_network_html_generator, agent_network_tester, email_sender
  - agent_network_html_generator (Coded Tool)
  - agent_network_tester (Coded Tool)
  - email_sender (Coded Tool)

Metadata: {
  "description": "Multi-agent system that automates the design, visualization, testing, and sharing of agent \
networks. Invokes agent_network_designer to generate HOCON configuration, creates HTML visualizations, demonstrates \
network functionality via Selenium testing, and sends results via email with attachments. Requires Chrome browser, \
Gmail API setup, and Selenium configuration.",
  "tags": [
    "agent_network",
    "email",
    "tool"
  ],
  "sample_queries": [
    "Design an agent network for a retail company",
    "Email it to john@example.com",
    "Create a multi-agent system for healthcare management",
    "Test it with a sample query",
    "Build and visualize an agent network for university administration"
  ]
}
```

## Lint Warnings

Beyond the hard validation rules above, the validator runs three best-effort lint checks. Unlike the rest of
validation, these can have legitimate explanations the hocon file alone can't rule out (a sly_data key set only
by a CodedTool at runtime, for instance), so they are printed as warnings and do not affect the exit code unless
you pass `--strict`:

- **Unused commondefs** - a `commondefs.replacement_strings` or `commondefs.replacement_values` entry that is
  never referenced (as `{key}` or as a bare value, respectively) anywhere else in the file. Usually a stale
  definition left over from a refactor.
- **Unresolved `{replacement}` strings** - a `{word}`-shaped placeholder that survives commondefs substitution,
  almost always because of a typo in the token or a missing `commondefs.replacement_strings` entry.
- **`allow.*.sly_data` keys that are never set** - a key referenced under `allow.to_downstream.sly_data`,
  `allow.from_downstream.sly_data`, `allow.to_upstream.sly_data`, or `allow.to_tracing.sly_data` that isn't
  declared in any `sly_data_schema`/`sly_data_output_schema` in the file. This one is necessarily approximate:
  a CodedTool can set a sly_data key at runtime with no schema anywhere, and a key can be declared by an
  externally-referenced agent network (one reached via `/some_agent`) that this per-file check can't see.
  Treat a hit as "double check this", not proof of a bug.

Example output for a file with an unused commondef:

```text
Validation passed: No errors found.

1 lint warning(s) (use --strict to treat these as errors):

  1. commondefs.replacement_strings.operation is defined but '{operation}' never appears anywhere else in the network.
```

Pass `--strict` to make any of these warnings fail validation (exit code 1) instead:

```sh
python -m neuro_san.client.hocon_validator_cli registries/my_agent.hocon --strict
```
