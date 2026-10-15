# Agent Network Schema

[`docs/agent_network_schema.hocon`](./agent_network_schema.hocon) is a
[JSON Schema](https://json-schema.org) (draft 2020-12) describing the shape of a single agent network `.hocon`
file, as documented in [agent_hocon_reference.md](./agent_hocon_reference.md). It covers every key documented
there, and is intentionally permissive (`additionalProperties: true` throughout) since real agent networks
routinely carry CodedTool-, toolbox-, and middleware-specific keys this schema has no way to anticipate.

The schema file itself is written in HOCON so that inline `#` comments can explain non-obvious
fields. It parses to the same dictionary a `.json` version would.

Its purpose is to let simple scripts catch obvious shape mistakes (a typo'd key name, a `parameters` block
missing `properties`, an unsupported `type` string) before you ever get to `hocon_validator_cli` or a running
server.

## Validate the parsed config, not the raw text

HOCON is a superset of JSON, and the registries in this repo routinely use syntax a plain JSON/JSONC parser
rejects: unquoted keys (`metadata: {`), `#` comments, triple-quoted multi-line strings (`"""..."""`), and bare
`true`/`false`/`True`/`False`. A tool that maps this schema directly onto the raw `.hocon` text (via a JSON or
JSONC language mode) will likely flag that valid HOCON as a syntax error before it ever gets to check the
schema.

This schema is meant to be checked against the dictionary pyhocon/leaf-common produce after parsing: the same
dictionary `AgentNetworkRestorer` hands to neuro-san's own validators. That works regardless of which HOCON
surface syntax a given file leans on.

## Usage

### Script / CI / pre-commit

```python
from io import BytesIO
from jsonschema import Draft202012Validator
from leaf_common.serialization.format.hocon_serialization_format import HoconSerializationFormat
from neuro_san.internals.graph.persistence.agent_network_restorer import AgentNetworkRestorer

with open("docs/agent_network_schema.hocon", "rb") as f:
    schema = HoconSerializationFormat(sanitize_keys=True).to_object(BytesIO(f.read()))

restorer = AgentNetworkRestorer(registry_dir=None)
config = restorer.restore(file_reference="registries/my_agent.hocon").get_config()

for error in Draft202012Validator(schema).iter_errors(config):
    print(f"{'/'.join(str(p) for p in error.absolute_path)}: {error.message}")
```

For full validation (including lint checks), use
[`hocon_validator_cli`](./hocon_validator_cli.md) instead.
