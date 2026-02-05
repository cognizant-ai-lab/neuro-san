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
