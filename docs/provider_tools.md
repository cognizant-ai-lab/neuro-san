# Provider Tools

`provider_tools` lists tools that run on the model provider's servers rather than in neuro-san: web search,
code execution and similar built-ins. It is a key of [`llm_config`](./agent_hocon_reference.md#provider_tools),
at the network level or for one agent. The dictionaries are passed to the provider unchanged, so their shapes
must match the provider selected by `model_name` or `class`.

For tools that run in neuro-san or on your own servers, see the agent's
[`tools`](./agent_hocon_reference.md#tools-agents) list, [External Agents](./external_agents.md) and
[MCP Servers as Tools](./mcp_tools.md).

<!--TOC-->

- [Example](#example)
- [Inheritance and fallbacks](#inheritance-and-fallbacks)
- [Supported shapes per provider](#supported-shapes-per-provider)
- [Load-time validation](#load-time-validation)
- [Limitations](#limitations)

<!--TOC-->

## Example

```hocon
"llm_config": {
    "model_name": "gpt-5.2",
    "provider_tools": [
        {"type": "web_search"},
        {"type": "code_interpreter", "container": {"type": "auto"}}
    ]
}
```

The model decides whether to use a provider tool; neuro-san does not force a tool choice.

## Inheritance and fallbacks

An agent-level list replaces the network-level list. Set it to `[]` or `null` to clear inherited tools.

All entries in a fallback chain, including peer groups, must use the same provider when `provider_tools` is
non-empty, because LangChain binds the same list to every fallback.

`provider_tools` is not a class argument: neuro-san consumes the list when creating the agent and does not pass
it to the chat-model constructor.

## Supported shapes per provider

`provider_tools` is available for the `openai`, `azure-openai`, `anthropic`, and `gemini` classes. A class
supports `provider_tools` when its own `args` in the llm_info [`classes`](./llm_info_hocon_reference.md#classes)
table declare the `provider_tools` key; the stock file does this for `openai`, `azure-openai`, `anthropic` and
`gemini`, and a class in a user `llm_info_file` can opt in the same way. The key is not inherited through `extends`:
`azure-openai` declares it itself and, because it extends `openai`, takes the OpenAI dictionaries, while
`anthropic-bedrock` does not declare it and is not supported.

- OpenAI accepts Responses API built-ins such as `{"type": "web_search"}` and
  `{"type": "code_interpreter", "container": {"type": "auto"}}`. Provider tools require the Responses API; do
  not set `use_responses_api` to `false`. The same dictionaries apply to `azure-openai`, which reaches Azure's
  Responses API through the v1 endpoint. On Azure, web search is Grounding with Bing, billed separately, and a
  subscription admin can block it; not every OpenAI built-in is offered on Azure.
- Anthropic accepts server tools such as
  `{"type": "web_search_20250305", "name": "web_search", "max_uses": 5}`. Supported server-side families include
  `web_search_`, `web_fetch_`, `code_execution_`, `tool_search_`, and `mcp_toolset`. Client-side tools such as
  `bash_`, `text_editor_`, `computer_`, and `memory_` are not executed by neuro-san.
- Gemini accepts one built-in entry, such as `{"google_search": {}}` or `{"code_execution": {}}`. Do not combine
  a Gemini built-in with other provider tools or regular function tools.

## Load-time validation

When a network is read from the registry, deployed, or checked with the
[hocon validator CLI](./hocon_validator_cli.md), the following `provider_tools` mistakes are reported as validation
errors, so they surface then rather than as provider errors at request time:

- `provider_tools` that is not a list, or a list containing something other than a dictionary.
- Near-miss spellings such as `provider_tool`, `builtin_tools`, `built_in_tools`, or `server_tools`, which the
  runtime would otherwise ignore silently.
- A `provider_tools` key inside a [fallbacks](./agent_hocon_reference.md#fallbacks) entry, which the runtime
  ignores; declare it at the top level of the `llm_config` so it applies to every fallback.
- `provider_tools` on an LLM agent whose `model_name`, short `class` value, or any fallback resolves to a class that
  does not support it, such as `ollama` or `anthropic-bedrock`.
- A fallback chain whose models resolve to more than one class while `provider_tools` is non-empty, since the same
  list is bound to every fallback and the runtime rejects such a chain.
- A dictionary that does not match the provider: a Gemini entry with a `type` key, an OpenAI or Anthropic entry
  without a string `type`, or an Anthropic `type` that is not a server tool. Anthropic client-side tools (`bash_`,
  `text_editor_`, `computer_`, `memory_`) are reported here because neuro-san does not execute them.
- An LLM agent whose `model_name`, short `class` value, or any fallback resolves to the `gemini` class and that
  declares `provider_tools` alongside other `tools`, or more than one Gemini built-in entry.

A model whose short `class` or `model_name` is not in llm_info, or whose `class` is a dotted path, resolves to no
llm_info class and is skipped by the last four rules. Coded tools and toolbox tools never build a model.

## Limitations

Provider tool activity and results are carried over neuro-san's text-only response and history interfaces. Provider
billing for searches, code execution, or other built-ins is separate from neuro-san's token accounting. Do not put
API keys or other secrets inside provider tool dictionaries; use the provider's normal credential configuration.

OpenAI built-in tools are available only through the Responses API, so `use_responses_api: false` cannot be used
with `provider_tools`. The `anthropic-bedrock`, `bedrock`, `ollama`, `nvidia`, and `openrouter` classes do not
support `provider_tools`; a network that declares it for one of them is reported at load time.
