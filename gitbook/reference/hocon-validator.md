# HOCON Validator

The `hocon_validator_cli` is a command-line tool for validating agent network HOCON
configuration files. It checks for structural errors, missing references, and invalid
configurations before you run the network.

## Usage

Validate all HOCON files in the default registry:

```bash
python -m neuro_san.client.hocon_validator_cli
```

### Verbose Output

Show detailed validation results for each file:

```bash
python -m neuro_san.client.hocon_validator_cli --verbose
```

### Custom Registry Directory

Validate files in a specific directory:

```bash
python -m neuro_san.client.hocon_validator_cli --registry-dir path/to/registries
```

### External Agents

When your network references external agents (agents on other servers), the validator
won't be able to resolve them locally. Specify them explicitly to suppress false errors:

```bash
python -m neuro_san.client.hocon_validator_cli --external-agents banking_ops hr_portal
```

## What It Validates

The validator checks for:

- **HOCON syntax** -- Parsing errors, malformed JSON/HOCON
- **Required fields** -- Missing `name`, `function`, or `instructions`
- **Tool references** -- Agent tools that reference non-existent agents
- **DAG structure** -- Circular dependencies between agents
- **CodedTool paths** -- Invalid Python class paths
- **LLM configuration** -- Missing or invalid model names

## Exit Codes

| Code | Meaning |
|:-----|:--------|
| 0 | All files valid |
| 1 | One or more validation errors found |

## Command-Line Flags

| Flag | Description |
|:-----|:------------|
| `--verbose` | Show detailed results for each file |
| `--registry-dir PATH` | Custom registry directory (default: auto-detected) |
| `--external-agents NAME [NAME ...]` | Agent names to treat as external |

## Example Output

```
$ python -m neuro_san.client.hocon_validator_cli --verbose

Validating registries...

  hello_world.hocon .............. OK
  weather_assistant.hocon ........ OK
  broken_agent.hocon ............. FAIL
    ERROR: Agent "data_fetcher" referenced in tools but not defined.

Results: 2 passed, 1 failed
```

## Integration with CI

Add HOCON validation to your CI pipeline:

```yaml
- name: Validate HOCON files
  run: python -m neuro_san.client.hocon_validator_cli
```
