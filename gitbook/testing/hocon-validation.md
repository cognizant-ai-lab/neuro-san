# HOCON Validation

Before running agent networks, validate your HOCON configuration files to catch errors
early.

## The HOCON Validator CLI

Neuro SAN includes a command-line tool for validating HOCON files:

```bash
python -m neuro_san.client.hocon_validator_cli
```

This scans all HOCON files in the default registry directory and reports any issues.

## Verbose Mode

See detailed results for each file:

```bash
python -m neuro_san.client.hocon_validator_cli --verbose
```

## Custom Registry Directory

Validate files in a specific directory:

```bash
python -m neuro_san.client.hocon_validator_cli --registry-dir path/to/registries
```

## External Agents

If your networks reference agents on other servers, tell the validator about them
to suppress false errors:

```bash
python -m neuro_san.client.hocon_validator_cli --external-agents banking_ops hr_portal
```

## What Gets Validated

- HOCON syntax and parsing
- Required fields (name, function, instructions)
- Tool references (all referenced agents exist)
- DAG structure (no circular dependencies)
- CodedTool class paths
- LLM configuration validity

## Markdown Linting

Neuro SAN also supports markdown linting for documentation files:

```bash
pymarkdown scan docs/
```

## CI Integration

Add validation to your CI pipeline:

```yaml
steps:
  - name: Validate HOCON
    run: python -m neuro_san.client.hocon_validator_cli

  - name: Lint Markdown
    run: pymarkdown scan docs/
```

## Next Steps

- [HOCON Validator Reference](../reference/hocon-validator.md) -- Complete CLI reference
- [Running Tests](running-tests.md) -- Automated testing
