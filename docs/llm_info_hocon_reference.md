# LLM Info HOCON File Reference

This document describes the neuro-san specifications for the llm_info.hocon file
which allows for extending the default descriptions of llms shipped with the neuro-san library.

The neuro-san system uses the HOCON (Human-Optimized Config Object Notation) file format
for its data-driven configuration elements.  Very simply put, you can think of
.hocon files as JSON files that allow comments, but there is more to the hocon
format than that which you can explore on your own.

Specifications in this document each have header changes for the depth of scope of the dictionary
header they pertain to.
Some key descriptions refer to values that are dictionaries.
Sub-keys to those dictionaries will be described in the next-level down heading scope from their parent.

<!--TOC-->

- [LLM Info HOCON File Reference](#llm-info-hocon-file-reference)
    - [LLM Info Specifications](#llm-info-specifications)
        - [Model Name Keys](#model-name-keys)
            - [class](#class)
            - [model_info_url](#model_info_url)
            - [modalities](#modalities)
                - [input](#input)
                - [output](#output)
            - [capabilities](#capabilities)
            - [context_window_size](#context_window_size)
            - [max_output_tokens](#max_output_tokens)
            - [knowledge_cutoff](#knowledge_cutoff)
            - [price_per_1k_input_tokens](#price_per_1k_input_tokens)
            - [price_per_1k_output_tokens](#price_per_1k_output_tokens)
            - [model_launch_date](#model_launch_date)
            - [model_retirement_date](#model_retirement_date)
            - [use_model_name](#use_model_name)
        - [classes](#classes)
            - [Class Name Keys](#class-name-keys)
                - [extends](#extends)
                - [args](#args)
            - [factories](#factories)
        - [default_config](#default_config)
    - [Provider-Specific Arguments](#provider-specific-arguments)
        - [OpenAI Reasoning and Responses API Parameters](#openai-reasoning-and-responses-api-parameters)
        - [Anthropic Thinking Parameters](#anthropic-thinking-parameters)
        - [Gemini Thinking Parameters](#gemini-thinking-parameters)
    - [Extending LLM Info Specifications](#extending-llm-info-specifications)
        - [AGENT_LLM_INFO_FILE environment variable](#agent_llm_info_file-environment-variable)
        - [llm_info_file key in specific agent hocon files](#llm_info_file-keys-in-agent-network-hocon)

<!--TOC-->

## LLM Info Specifications

All parameters listed here have global scope and are listed at the top of the file by convention.

The default file used with the system is called
[default_llm_info.hocon](../neuro_san/internals/run_context/langchain/llms/default_llm_info.hocon).

### Model Name Keys

Top-level keys in the file correspond to newly defined usable names for models an the agent network's
[llm_config](./agent_hocon_reference.md#model_name).

The value for any model name key is a dictionary describing the model itself, which the next few headings
will describe.

#### `class`

The `class` is a string descriptor that refers to an entry in the [`classes`](#classes) table below.
Nominally each class corresponds to a single LLM provider that has its own instance of langchain's
BaseLanguageModel, and therefore its own class to construct upon initiating a new LLM-powered agent
for use in the agent network.

Most often, a single BaseLanguageModel class will support multiple models.

#### `model_info_url`

A URL string that points to the information page for details on the given model.

The idea here is that agent network developers can check this URL as a reference when
LLM performance does not match expectations.

#### `modalities`

A dictionary that describes the I/O capabilities that the LLM "speaks".

The keys to this dictionary are described immediately below.

##### `input`

A list of strings describing the input modalities of the LLM.
Some common input modalities include:

- text
- image

Typically, an LLM will at least have a "text" modality but might have more than one.

Note it is not possible to simply list a new input type and have the capability
magically manifest itself.  This is a matter of how the LLM was trained.

##### `output`

A list of strings describing the output modalities of the LLM.
Some common output modalities include:

- text
- image

Typically, an LLM will at least have a "text" modality but might have more than one.

Note it is not possible to simply list a new output type and have the capability
magically manifest itself.  This is a matter of how the LLM was trained.

#### `capabilities`

A list of strings describing the capabilities the LLM has been trained on.

- tools

Currently the only capability that matters to neuro-san is an LLM's capability
to use tools. Any intermediate LLM-powered agent in neuro-san requires the use of tools
in order to be able to call its downstream agents. Normally a model's [`model_info_url`](#model_info_url)
will say whether or not a given model is tool-using or not.  If it doesn't say that it
is trained to use tools, it typically does not.

The lack of capability to use tools is the main source of disappointment for neuro-san
users when trying out newly released models.

Some newer OpenAI models are trained to use tools but only do so through the Responses API
(for example `gpt-6-astra`), or need `reasoning_effort` set to `"none"` to use tools on Chat Completions
(the `gpt-5.6-*` models). Which OpenAI endpoint a model uses is controlled by `use_responses_api` in the
`llm_config`, or by the `openai` class default in this file. See
[OpenAI Reasoning and Responses API Parameters](#openai-reasoning-and-responses-api-parameters)
for the per-model details.

Note it is not possible to simply list a new capability and have it
magically manifest itself.  This is a matter of how the LLM was trained.

#### `context_window_size`

The maximum number of tokens allowed by the model as input.
This number typically includes chat history for the LLM as well as any new user input,
and/or RAG document.

While it is possible to specify a smaller context_window_size in a given [`classes`](#classes)
configuration, it is not possible to simply list a new larger value and have it
magically manifest itself.  This is a matter of how the LLM was trained.

#### `max_output_tokens`

The maximum number of tokens allowed by the model as output for any given answer.
This number typically excludes chat history for the LLM.

While it is possible to specify a smaller max_output_tokens in a given [classes](#classes)
configuration, it is not possible to simply list a new larger value and have it
magically manifest itself.  This is a matter of how the LLM was trained.

**`null` is allowed** for entries whose true output ceiling is not known ahead of time.
The motivating case is OpenRouter's meta-router models (e.g. `openrouter/free`,
`openrouter/auto`), which pick an underlying model at request time, so the real
`max_output_tokens` varies per request. When `max_output_tokens` is `null`, neuro-san
skips the `prompt_token_fraction` multiplication and leaves the resulting `max_tokens`
unset on the LLM, letting the provider's own default take over. Concrete numeric values
are still preferred whenever the model has a known fixed ceiling — `null` should be
reserved for the cases above.

#### `knowledge_cutoff`

String date indicating the origination date of the last piece of training data.

The lack of current knowledge is another common source of disappointment for neuro-san
users when trying out newly released models.

#### `price_per_1k_input_tokens`

A floating-point number indicating the cost in US dollars to process 1,000 input tokens
through the model. Input tokens include the prompt, chat history, system messages, tools,
and any other content sent to the model.

This value is typically sourced from the LLM provider's pricing page (see the comment near
the price fields in the default file for the relevant URL). Providers change pricing
periodically, so this number should be treated as a snapshot at the time the entry was
authored.

This key is optional, but the prices in the LLM info file are the only source used for token-cost
estimation in the token callback handler. If no price information is found for a model, the
reported cost defaults to 0 and a warning is logged.
If a model has tiered or context-dependent pricing, the value here should be the standard published rate.

#### `price_per_1k_output_tokens`

A floating-point number indicating the cost in US dollars to generate 1,000 output tokens
from the model. Output tokens are the tokens the model produces in its response.

For most providers, output tokens are billed at a higher rate than input tokens.

This key is optional and follows the same caveats as
[`price_per_1k_input_tokens`](#price_per_1k_input_tokens): prices in the LLM info file are the
only source used for token-cost estimation, and a model without price information reports a
cost of 0 with a logged warning.

#### `model_launch_date`

A string in `YYYY-MM-DD` format indicating the date the model first became available on
its provider's API.

This is sourced from the provider's official release notes or model card (for example,
the AWS Bedrock model cards for Anthropic models, OpenAI's release notes for OpenAI models,
or the Gemini API deprecations page for Gemini models). Note that the date encoded in a
model ID's suffix (e.g. `claude-sonnet-4-20250514`) is the model snapshot date, which is
not always the same as the public launch date — prefer the provider's stated launch date
over the ID suffix.

This key is optional. It is informational only and is not consumed by neuro-san at runtime.

#### `model_retirement_date`

A string in `YYYY-MM-DD` format indicating the date the model is scheduled to be retired
(shut down) on its provider's API, or `null` if no retirement date has been announced.

For active models, some providers (notably Anthropic and Google) publish "earliest
possible" or "not sooner than" retirement dates that may be pushed out — the value here
reflects the provider's published date at the time the entry was authored.

This key is optional. It is informational only and is not consumed by neuro-san at runtime,
but is useful for tracking which models in your configuration are approaching end-of-life.

#### `use_model_name`

A string which allows aliasing of model names.

Often times official model version strings will have a date or other versioning string associated
with them. New models will become available under a particular version number, but the official
shorter designation might not change until the robustness of the model can be verified. In case
specific functionality of a model version is required, referring to the full model version is
usually maintained for backwards compatibility.

For example, "gpt-4o-2024-08-06" is one of the official names for "gpt-4o", but before that one
became the official "gpt-4o", there was another version called "gpt-4o-2024-05-13".

You can use the `use_model_name` key for your own model aliasing purposes as well however you like.

### `classes`

A dictionary describing the details needed to instatiate the class of langchain BaseLanguageModel
used for particular model.  Typically a single class is used for all models from a particular
LLM provider and neuro-san provides stock class definitions for popular LLM providers like
OpenAI, Anthropic, NVidia, and Ollama.

It is possible to provide your own extensions to existing classes to allow for different
constructor defaults to existing LLM classes.  This is especially necessary when specifying
your own endpoints to private model instances, for example.

Also, as new LLM providers emerge, this mechanism can be extended to specify a new
langchain BaseLanguageModel with a combination of data-driven and coded manners.

The data-driven keys in this dictionary are described below.

See the entry for [`factories`](#factories) below for further instructions as to how
to extend neuro-san with new BaseLanguageModel implementations.

#### Class Name Keys

In general, the keys in the classes dictionary are the names of the classes themselves,
and it is these keys which are used in the model definition's [`class`](#class) key described above.
The values are dictionaries that describe configurable data associated with each BaseLanguageModel
class.

##### `extends`

An optional key with a string value that points to another class definition within the
[`classes`](#classes) dictionary.

The idea is to allow the data-driven defaults to inherit
from previous definitions just like the Python implementations can, allowing overriding
some values while also avoiding repetition.

##### `args`

A dictionary whose keys are names of fields in the BaseLanguageModel's constructor,
and the values are default values to use.

Typically this dictionary of arguments contains values that are the coded defaults,
but it is possible to have your own extensions provide their own defaults.  This is
especially useful in combination with model aliasing when privately hosted LLMs
need to specify specific endpoints that are used over and over again in your agent
definitions.

The arguments of the stock classes whose effect is not obvious from their name are described in
[Provider-Specific Arguments](#provider-specific-arguments) below.

#### `factories`

You can list your own factory classes that create a BaseLanguageModel instance given a config if the
stock neuro-san LLMs do not suit your needs.  An example entry within the classes dictionary would
look like this:

```hocon
"factories": [ "my_package.my_module.MyLangChainLlmFactory" ],
```

Any classes listed must:

- Exist in the `PYTHONPATH` of your server
- Have a no-args constructor
- Either:
  - Derive from `neuro_san.internals.run_context.langchain.llms.standard_langchain_llm_factory.StandardLangChainLlmFactory`
    to supply a mapping of class name to neuro_san.internals.run_context.langchain.llms.llm_policy.LlmPolicy
    class implementations (preferred - see `tests.neuro_san.intnrnals.run_context.langchain.llms.test_llm_factory`).   OR
  - Derive from `neuro_san.internals.run_context.langchain.llms.langchain_llm_factory.LangChainLlmFactory`
    to override the `create_llm_resources()` method that creates LangChainLlmResources object.  OR
  - Derive from `neuro_san.internals.run_context.langchain.llms.langchain_llm_factory.LangChainLlmFactory`
    to override the `create_base_chat_model()` method that creates your BaseLanguageModel instance. (legacy)

### `default_config`

A dictionary that describes the default configuration for any agent's `llm_config`, allowing
you to tweak the default to your own preferred least common denominator.

Any combination of [`llm_config`](./agent_hocon_reference.md#llm_config) and/or [`args`](#args)
can be specified here.

## Provider-Specific Arguments

Most entries in a stock class's [`args`](#args) map one-to-one onto constructor arguments of the langchain chat
model and need no explanation beyond their name. The ones below do: they decide which endpoint a request goes
to, or some models reject them. The values quoted here are the class defaults in
[default_llm_info.hocon](../neuro_san/internals/run_context/langchain/llms/default_llm_info.hocon). Any of them
can be overridden for one agent in its [`llm_config`](./agent_hocon_reference.md#llm_config), or for a whole
server by pointing the [`AGENT_LLM_INFO_FILE`](#agent_llm_info_file-environment-variable) environment variable
at a sparse llm info file that deep-merges over the default. An agent network that sets its own
[`llm_info_file`](#llm_info_file-keys-in-agent-network-hocon) ignores that variable and needs the override in
that file instead.

### OpenAI Reasoning and Responses API Parameters

The `openai` class accepts a few parameters that only matter for OpenAI reasoning models and for choosing which
OpenAI endpoint (Chat Completions or the Responses API) requests are sent to. The Responses API is the default
endpoint, because OpenAI's newest models only support tool calling combined with reasoning there (see
"Models that need the Responses API for tool calling" below). Responses are not stored server-side by default,
and the reasoning parameters default to `null`.

- `reasoning`: a dictionary passed through as the Responses API `reasoning` object, for example
  `{"effort": "low", "summary": "auto"}`. Setting it makes langchain route requests to the Responses API even
  when `use_responses_api` is `null`.
- `reasoning_effort`: a string such as `"low"`, `"medium"` or `"high"` that constrains how much reasoning the
  model does (`"none"` disables reasoning on models that allow it, such as `gpt-5.6-*`; `gpt-6-astra` rejects
  it). On the Chat Completions path it is sent as-is. On the Responses API path langchain folds it into
  `reasoning.effort` **only when `reasoning` is absent**, so set either `reasoning` or `reasoning_effort`, not
  both. Setting `reasoning_effort` on its own does not change the endpoint.
- `verbosity`: a string (`"low"`, `"medium"` or `"high"`) that controls how long the model's answers are.
- `use_responses_api`: a tri-state switch for the endpoint:
    - `true` (the default): every OpenAI model uses the Responses API. This is the endpoint OpenAI's newest
      models require for tool calling with reasoning (see below); OpenAI's
      [migration guide](https://developers.openai.com/api/docs/guides/migrate-to-responses) describes the
      differences from Chat Completions.
    - `false`: always use Chat Completions. Use this for OpenAI-compatible gateways that only implement
      `/chat/completions`. To switch a single agent, set it in that agent's `llm_config`. To switch a whole
      server, point the [AGENT_LLM_INFO_FILE](#agent_llm_info_file-environment-variable) environment variable
      at a sparse llm info file that deep-merges over the default. An agent network that sets its own
      [llm_info_file](#llm_info_file-keys-in-agent-network-hocon) ignores the environment variable, so it needs
      the same override in that file:

      ```hocon
      {
          "classes": {
              "openai": {
                  "args": {
                      "use_responses_api": false
                  }
              }
          }
      }
      ```

    - `null`: let langchain infer the endpoint from the other parameters and the model name, as documented for
      [`use_responses_api`](https://reference.langchain.com/python/langchain-openai/chat_models/base/BaseChatOpenAI/use_responses_api).
      langchain switches to the Responses API when any Responses-only setting is present (`reasoning`, `include`,
      `truncation`, `context_management`, `previous_response_id`, `text`, or a built-in tool such as web search)
      or when the model is one it knows to be Responses-only (the `gpt-5.x-pro` and `codex` models); otherwise it
      uses Chat Completions. Of those settings, the `openai` class only exposes `reasoning`, `include` and the
      model name. This was the default before the Responses API became the default endpoint.
- `store`: whether OpenAI keeps the response server-side (`false` by default). OpenAI stores responses for 30
  days unless told otherwise; `false` makes every request stateless. Stateless operation does not break
  reasoning models in the tool-calling loop, because the Responses API includes an `encrypted_content` property
  on reasoning items by default (see the
  [OpenAI reasoning guide](https://developers.openai.com/api/docs/guides/reasoning)) and langchain replays those
  items on the next turn. Set `true` to let OpenAI store responses so they can be retrieved later, or `null` to
  omit the field entirely for gateways that reject fields they do not know. Chat Completions accepts `store` too.
- `include`: a list of extra output fields to return, for example `["reasoning.encrypted_content"]` (`null` by
  default). OpenAI still accepts that legacy value but no longer requires it, because `encrypted_content` is
  included by default. Any non-null `include` makes langchain route to the Responses API when `use_responses_api`
  is `null`, while an explicit `"use_responses_api": false` still wins and then Chat Completions rejects the
  parameter outright, so leave it `null` unless the request is certain to go to the Responses API.

**Models that need the Responses API for tool calling.** OpenAI's newest models no longer accept function (tool)
calls together with reasoning on Chat Completions, and every agent that lists `tools` is a tool-calling agent.
A Chat Completions request from a `gpt-5.6-*` model that carries tools is rejected with an error such as:

> Function tools with reasoning_effort are not supported for gpt-5.6-sol in /v1/chat/completions.
> To use function tools, use /v1/responses or set reasoning_effort to 'none'.

With the Responses API as the default endpoint both model families work out of the box. They differ in how far
you can move away from the defaults:

- `gpt-5.6-*` (`gpt-5.6-sol`, `gpt-5.6-terra`, `gpt-5.6-luna`): the defaults keep reasoning and tool calling.
  If you must stay on Chat Completions, set `"use_responses_api": false` together with
  `"reasoning_effort": "none"`, which makes tool calls work but without any reasoning.
- `gpt-6-astra`: the Responses API is the only option, so never set `"use_responses_api": false` for it. The
  [OpenAI reasoning guide](https://developers.openai.com/api/docs/guides/reasoning) states that
  "Chat Completions does not support function calling with GPT-6 Astra" and that GPT-6 Astra
  "does not support none reasoning effort" (the API answers HTTP 400), so the `"none"` workaround does not exist
  for it.

The minimal configuration is just the model name. The model's default reasoning effort applies; add
`reasoning_effort` only when you want a different level.

```hocon
"llm_config": {
    "model_name": "gpt-6-astra"
}
```

**Parameters the Responses API rejects.** `presence_penalty`, `frequency_penalty`, `seed`, `logprobs` and
`logit_bias` exist only on Chat Completions. Now that the Responses API is the default endpoint, an llm_config
that carries any of them is rejected unless it also sets `"use_responses_api": false`, so remove them from every
other OpenAI llm_config. `stop` is Chat Completions only as well, but langchain-openai drops it from Responses API
requests instead of failing, so it simply has no effect unless `use_responses_api` is `false`. OpenAI's
[migration guide](https://developers.openai.com/api/docs/guides/migrate-to-responses) lists the remaining
differences between the two endpoints.

**Interaction with fallbacks.** The rejections above surface as exceptions on the client side, but
[fallbacks](./agent_hocon_reference.md#fallbacks) wrap the model so that any exception moves on to the next
llm_config in the list. With fallbacks configured, a misconfigured primary model silently fails over instead of
reporting the problem, so verify a new llm_config without fallbacks first.

**Azure OpenAI.** The `azure-openai` class extends `openai` and therefore inherits the `use_responses_api`,
`store` and `include` defaults, but `AzureLlmPolicy` does not forward any of them to `AzureChatOpenAI`, so those
keys have no effect on Azure. Azure requests instead follow langchain's own inference: Chat Completions for most
models, but a model name langchain knows to be Responses-only (such as the `gpt-5.4-pro` snapshot behind
`azure-gpt-5.4-pro`) auto-routes to the Responses API, which `AzureLlmPolicy` does not support yet. Responses API
support for Azure, including pinning the endpoint, is tracked in
[#1307](https://github.com/cognizant-ai-lab/neuro-san/issues/1307).

**OpenAI-compatible gateways such as LiteLLM.** A neuro-san llm_config reaches a gateway through the `openai`
class with `openai_api_base` pointing at it, so the gateway receives whatever the `openai` class sends: with the
defaults above that is a request to `/v1/responses` carrying `store: false`. What happens next depends on the
gateway:

- A gateway that fronts OpenAI and serves `/v1/responses` (LiteLLM does, for every provider it supports) needs
  no change. The requests carry the same parameters as before plus `store: false`, which OpenAI accepts on
  both endpoints.
- A gateway that only implements `/chat/completions`, such as an older proxy or the bundled mock and
  record/playback test servers, needs `"use_responses_api": false`.
- A gateway that translates the OpenAI format into another provider's API, such as LiteLLM with an Anthropic,
  Bedrock or Gemini model behind an OpenAI-style alias, checks every OpenAI parameter against that provider
  and rejects `store`, which those providers do not have, unless it is configured to drop unsupported
  parameters (`drop_params: true` in LiteLLM). Set `"store": null` so that the field is omitted entirely.

Either override can be made per agent in its `llm_config` or server-wide with a sparse llm info file, exactly as
shown for `use_responses_api` above. Pinning Chat Completions and omitting `store` together restores the
requests neuro-san sent before the Responses API became the default:

```hocon
{
    "classes": {
        "openai": {
            "args": {
                "use_responses_api": false,
                "store": null
            }
        }
    }
}
```

**Upgrading existing OpenAI configurations.** Making the Responses API the default changes a few observable
things for llm_configs that never set `use_responses_api`:

- Requests go to `/v1/responses` instead of `/v1/chat/completions`. Against OpenAI itself nothing needs to
  change; gateways are covered in the previous paragraph.
- Responses are no longer stored server-side, because `store` defaults to `false`. Set `"store": true` if you
  relied on retrieving responses from OpenAI afterwards.
- `stop` sequences are ignored: the Responses API has no `stop` parameter and langchain-openai drops it from the
  request. They still apply with `"use_responses_api": false`.
- neuro-san now requires langchain-openai 1.4 or later (and langchain-core 1.5 or later, which it depends on).
  Earlier langchain-openai releases sent `stop` to the Responses API and lacked the stateless reasoning replay
  that `store: false` relies on.
- `tests/mock_llm_server/llm_info_chat_completions.hocon` is a ready-made server-wide override that pins the
  bundled test servers, and any other Chat-Completions-only gateway, back to `/chat/completions`.

### Anthropic Thinking Parameters

The `anthropic` and `anthropic-bedrock` classes expose `thinking`, `effort`, `temperature`, `top_p` and `top_k`,
but current Claude models are much stricter about them than earlier generations. On Claude Fable 5.1, Mythos 5.1,
Fable 5, Opus 5, Sonnet 5, Opus 4.8 and Opus 4.7 the API returns HTTP 400 for:

- any non-default `temperature`, `top_p` or `top_k`, whether or not thinking is used;
- `thinking` set to `{"type": "enabled", "budget_tokens": N}`, because these models only support adaptive thinking;
- `thinking` set to `{"type": "disabled"}` on Fable 5.1, Mythos 5.1 and Fable 5, where thinking is always on
  (Opus 5 also rejects it when `effort` is `"xhigh"` or `"max"`).

Leave `temperature`, `top_p`, `top_k` and `thinking` at their `null` defaults so that they are omitted from the
request, and use `effort` to steer how much the model thinks: `"low"`, `"medium"` or `"high"` (the API default),
plus `"xhigh"` and `"max"`, which the
[effort guide](https://platform.claude.com/docs/en/build-with-claude/effort#effort-levels) lists as available on
every model named above. See the
[Anthropic extended thinking guide](https://platform.claude.com/docs/en/build-with-claude/extended-thinking)
for the migration path from `budget_tokens` to `effort`, and the
[troubleshooting thinking](https://platform.claude.com/docs/en/build-with-claude/thinking-troubleshooting) page
for the per-model table of accepted `thinking` types.

### Gemini Thinking Parameters

The `gemini` class accepts a few parameters that only matter for Gemini thinking models. All of them default to
`null`, which leaves the model's own defaults in place.

- `thinking_level`: a string that constrains how much thinking the model does. The accepted values depend on the
  model (see the [Gemini 3 developer guide](https://ai.google.dev/gemini-api/docs/gemini-3#thinking_level) and
  the per-model pages under [Gemini models](https://ai.google.dev/gemini-api/docs/models)), and the API rejects
  a value the model does not support:
    - Gemini 3 Pro: `"low"` or `"high"` (default `"high"`).
    - Gemini 3 Flash: `"minimal"`, `"low"`, `"medium"` or `"high"` (default `"high"`).
    - Gemini 3.7 Flash and Gemini 3.8 Flash: `"low"`, `"medium"` or `"high"` (default `"medium"`). `"minimal"`
      is not supported and returns an error.
- `thinking_budget`: an integer number of thinking tokens for Gemini 2.5 models. `0` disables thinking where the
  model allows it, `-1` lets the model decide, and a positive integer caps the budget. Gemini 3 and later use
  `thinking_level` instead; when both are set, langchain keeps `thinking_level` and drops `thinking_budget`.
- `include_thoughts`: a boolean. When `true`, Gemini adds its thought summaries to the reply as thinking blocks
  in the message content. A summary is not guaranteed on every reply: the model may reason without emitting one.
  Thought signatures, which carry the model's reasoning across tool calls within a request, round-trip regardless
  of this setting. See the [Gemini thinking guide](https://ai.google.dev/gemini-api/docs/thinking) and the
  [langchain Gemini page](https://docs.langchain.com/oss/python/integrations/chat/google_generative_ai).

**Temperature.** Google recommends keeping `temperature` at `1.0` for Gemini 3 and later: lower values can cause
infinite loops, degraded reasoning and failures on complex tasks (see
[Gemini 3 temperature](https://ai.google.dev/gemini-api/docs/gemini-3#temperature)). The `gemini` class default
is `0.7`, so set `"temperature": 1.0` explicitly in the llm_config of any Gemini 3+ model.

```hocon
"llm_config": {
    "model_name": "gemini-3.8-flash",
    "temperature": 1.0,
    "thinking_level": "low",
    "include_thoughts": true
}
```

## Extending LLM Info Specifications

You can extend the list of LLMs available in the neuro-san system by providing your own llm info file
in one of the following ways:

### `AGENT_LLM_INFO_FILE` Environment Variable

Set the `AGENT_LLM_INFO_FILE` environment variable to specify a custom llm info file.
This applies system-wide and affects all agents running on the same server.

Use this approach if:

- You want to define a shared list of LLMs for all agents.

- You’re managing deployment at the server or container level.

### `llm_info_file` Keys in Agent Network HOCON

You can define a different llm info file for each agent by setting the
[`llm_info_file`](./agent_hocon_reference.md#llm_info_file)
key within the agent network HOCON file.

> Note: This key takes **precedence over** the `AGENT_LLM_INFO_FILE` environment variable.

Use this approach if:

- Different agents require different sets of LLMs.

- You want more granular control over model availability.
