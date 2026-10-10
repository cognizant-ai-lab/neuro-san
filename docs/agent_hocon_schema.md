# Agent Network JSON Schema

[`docs/schema/agent_network.schema.json`](./schema/agent_network.schema.json) is a
[JSON Schema](https://json-schema.org) (draft 2020-12) describing the shape of a single agent network `.hocon`
file, as documented in [agent_hocon_reference.md](./agent_hocon_reference.md). It covers every key documented
there, and is intentionally permissive (`additionalProperties: true` throughout) since real agent networks
routinely carry CodedTool-, toolbox-, and middleware-specific keys this schema has no way to anticipate.

Its purpose is to let editors and simple scripts catch obvious shape mistakes (a typo'd key name losing its
autocomplete, a `parameters` block missing `properties`, an unsupported `type` string) before you ever get to
`hocon_validator_cli` or a running server.

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
import json
from jsonschema import Draft202012Validator
from neuro_san.internals.graph.persistence.agent_network_restorer import AgentNetworkRestorer

with open("docs/schema/agent_network.schema.json") as schema_file:
    schema = json.load(schema_file)

restorer = AgentNetworkRestorer(registry_dir=None)
config = restorer.restore(file_reference="registries/my_agent.hocon").get_config()

for error in Draft202012Validator(schema).iter_errors(config):
    print(f"{'/'.join(str(p) for p in error.absolute_path)}: {error.message}")
```

### Editors with native HOCON + JSON Schema support

IntelliJ/PyCharm's bundled HOCON plugin lets you associate a JSON Schema with `.hocon` files the same way it
does for `.json`/`.yaml`: **Settings/Preferences -> Languages & Frameworks -> Schemas and DTDs -> JSON Schema
Mappings**. Point a mapping at `docs/schema/agent_network.schema.json` with a file pattern of
`registries/*.hocon`.

### Editors without native HOCON schema support (e.g. VSCode)

VSCode's built-in JSON language features (hover docs, autocomplete, `json.schemas`-based linting) only attach
to files recognized as JSON/JSONC; there is no first-party VSCode extension that applies a JSON Schema to
arbitrary `.hocon` text. Two practical options if you still want inline feedback:

1. Keep a given file to the JSON-compatible subset of HOCON (quoted keys, double-quoted strings, lowercase
   `true`/`false`, no `#` comments), associate it as `jsonc`, and add a `json.schemas` entry:

   ```jsonc
   // .vscode/settings.json
   {
     "files.associations": { "registries/my_agent.hocon": "jsonc" },
     "json.schemas": [
       {
         "fileMatch": ["registries/my_agent.hocon"],
         "url": "./docs/schema/agent_network.schema.json"
       }
     ]
   }
   ```

   This will misfire on any file using HOCON-only syntax, so treat it as opt-in per file rather than a blanket
   `registries/*.hocon` pattern unless your registries avoid that syntax.

2. Otherwise, rely on [`hocon_validator_cli`](./hocon_validator_cli.md) and the script snippet above for
   CI/pre-commit, and skip live editor squiggles for files that use full HOCON syntax.
