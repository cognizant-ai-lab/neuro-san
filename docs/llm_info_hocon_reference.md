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
            - [use_model_name](#use_model_name)
        - [classes](#classes)
            - [Class Name Keys](#class-name-keys)
                - [extends](#extends)
                - [args](#args)
            - [factories](#factories)
        - [default_config](#default_config)
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

#### `knowledge_cutoff`

String date indicating the origination date of the last piece of training data.

The lack of current knowledge is another common source of disappointment for neuro-san
users when trying out newly released models.

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

#### `factories`

You can list your own factory classes that create a BaseLanguageModel instance given a config if the
stock neuro-san LLMs do not suit your needs.  An example entry within the classes dictionary would
look like this:

    "factories": [ "my_package.my_module.MyLangChainLlmFactory" ],

Any classes listed must:

- Exist in the `PYTHONPATH` of your server
- Derive from `neuro_san.internals.run_context.langchain.llms.langchain_llm_factory.LangChainLlmFactory`
  to override the `create_base_chat_model()` method that creates your BaseLanguageModel instance.
- Have a no-args constructor

### `default_config`

A dictionary that describes the default configuration for any agent's `llm_config`, allowing
you to tweak the default to your own preferred least common denominator.

Any combination of [`llm_config`](./agent_hocon_reference.md#llm_config) and/or [`args`](#args)
can be specified here.

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
