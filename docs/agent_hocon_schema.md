# Agent Network Schema

[`docs/agent_network_schema.hocon`](./agent_network_schema.hocon) is a
[JSON Schema](https://json-schema.org) (draft 2020-12) describing the shape of a single agent network `.hocon`
file, as documented in [agent_hocon_reference.md](./agent_hocon_reference.md). It is intentionally permissive
(`additionalProperties: true` throughout) since real agent networks routinely carry CodedTool-, toolbox-, and
middleware-specific keys this schema has no way to anticipate.

The schema file itself is written in HOCON so that inline `#` comments can explain non-obvious fields. It
parses to the same dictionary a `.json` version would.

## What this schema catches

Running the schema against a parsed agent network reliably flags:

- wrong value types for the keys it names (for example, a string where a number is expected, or `temperature`
  given a non-numeric value);
- an unsupported `type` string inside a `parameters`/`sly_data_schema` property;
- an agent spec missing the required `name` field, or a top-level config missing `tools`;
- an agent name with disallowed characters (anything outside `[A-Za-z0-9_-]`).

## What it does not catch

Because `additionalProperties: true` is set almost everywhere and most property blocks are optional, the schema
does **not** catch:

- a typo'd key name (`instuctions` instead of `instructions`) — it is treated as an unknown extra key;
- a `parameters` block that omits `properties` entirely;
- missing or wrong values for keys the schema does not model (today this includes `provider_tools` and
  `function.invocation`, among others).

For those checks, use [`hocon_validator_cli`](./hocon_validator_cli.md), which runs the full neuro-san
validation chain.

## Validate the parsed config, not the raw text

HOCON is a superset of JSON, and the registries in this repo routinely use syntax a plain JSON/JSONC parser
rejects: unquoted keys (`metadata: {`), `#` comments, triple-quoted multi-line strings (`"""..."""`), and bare
`true`/`false`/`True`/`False`. A tool that maps this schema directly onto the raw `.hocon` text (via a JSON or
JSONC language mode) will likely flag that valid HOCON as a syntax error before it ever gets to check the
schema.

The schema is meant to be checked against the dictionary that falls out of parsing — the same shape neuro-san's
own validators work on — not the raw HOCON text.

## Load it with key sanitizing enabled

When the schema file is parsed back into a dictionary for use with a JSON Schema validator, the HOCON parser
must be configured to strip the quotes around keys that had to be quoted in the source (`$schema`, `$ref`,
`$defs`) — load it with key sanitizing enabled (`sanitize_keys=True`). Without it, the `$`-keys come back
carrying their quotes and the schema silently matches everything.

For full validation, use [`hocon_validator_cli`](./hocon_validator_cli.md): it runs the full neuro-san
validation chain described in that document.
