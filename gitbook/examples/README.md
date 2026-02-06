# Examples

Neuro SAN Studio ships with dozens of ready-to-run agent network examples organized by
complexity and domain. Each example demonstrates specific patterns and capabilities.

## Running Examples

All examples are available in [Neuro SAN Studio](https://github.com/cognizant-ai-lab/neuro-san-studio).
After installation, run any example:

```bash
python -m neuro_san.client.agent_cli --agent basic/music_nerd
```

Or use the web UI at [http://localhost:4173/](http://localhost:4173/) after starting Studio.

## Basic Examples

Introductory networks for learning core concepts.

| Example | Description | Key Concept |
|:--------|:------------|:------------|
| `basic/hello_world` | Two-agent greeting network | Agent delegation |
| `basic/music_nerd` | Music knowledge assistant | Single agent |
| `basic/music_nerd_pro` | Music assistant with CodedTools | CodedTools |
| `basic/coffee_finder` | Finds coffee using AAOSA | AAOSA protocol |
| `basic/coffee_finder_advanced` | Enhanced coffee finder with context | sly\_data |
| `basic/intranet_agent` | Internal knowledge base agent | Multi-agent hierarchy |
| `basic/math_olympiad` | Math competition solver | Reasoning chains |
| `basic/hypothesis_maker` | Scientific hypothesis generator | Creative reasoning |
| `basic/trip_planner` | Travel planning with sub-agents | Branching delegation |
| `basic/debate_team` | Multi-perspective debate | Parallel agents |
| `basic/kwik_agents` | Quick utility agents | Lightweight agents |
| `basic/smart_home` | Smart home automation | IoT-style agents |

### hello\_world

The simplest example. A greeter Front Man delegates to an announcement\_maker to create
a two-word greeting.

```
User → greeter_front_man → announcement_maker → "Hello, Mars!"
```

### coffee\_finder

Demonstrates the AAOSA protocol. Multiple coffee-finding agents (coffee shop, cafeteria,
vending machine) self-select based on context.

```
User → coffee_finder → coffee_shop_locator
                      → cafeteria_agent
                      → vending_machine_finder
```

### music\_nerd\_pro

Extends the basic music\_nerd with CodedTools for looking up actual song data and lyrics.
Demonstrates how to combine LLM reasoning with real data retrieval.

## Tool Integration Examples

Networks that demonstrate integration with external tools and services.

| Example | Description | Tools Used |
|:--------|:------------|:-----------|
| `tools/arxiv_retriever` | Search and summarize arXiv papers | arXiv RAG |
| `tools/brave_search_agent` | Web search via Brave | Brave Search |
| `tools/code_executor` | Execute Python code | Code execution |
| `tools/confluence_rag_agent` | Search Confluence wikis | Confluence RAG |
| `tools/docling_rag` | Document processing and RAG | Document RAG |
| `tools/gmail_assistant` | Read and send Gmail | Gmail toolkit |
| `tools/image_generator` | Generate images from text | Image generation |
| `tools/jira_assistant` | Manage Jira tickets | Jira toolkit |
| `tools/openai_web_search_agent` | Web search via OpenAI | OpenAI Search |
| `tools/pdf_rag` | Query PDF documents | PDF RAG |
| `tools/requests_get` | Make HTTP requests | HTTP toolkit |
| `tools/tavily_search_agent` | Web search via Tavily | Tavily Search |
| `tools/webpage_rag` | Extract and query web pages | Webpage RAG |
| `tools/wikipedia_rag` | Search Wikipedia | Wikipedia RAG |

## Industry Examples

Domain-specific solutions for real-world use cases.

| Example | Description | Domain |
|:--------|:------------|:-------|
| `industry/airline_policy` | Airline policy assistance | Aviation |
| `industry/banking_ops` | Banking operations | Finance |
| `industry/insurance_claims` | Claims processing | Insurance |
| `industry/medical_records` | Medical record analysis | Healthcare |
| `industry/real_estate` | Property search and analysis | Real Estate |
| `industry/retail_assistant` | Retail customer service | Retail |
| `industry/telco_agent` | Telecom customer support | Telecom |

### airline\_policy

A comprehensive example showing how multiple policy specialists (baggage, booking,
loyalty, safety) collaborate to answer customer questions. Uses AAOSA for routing.

### banking\_ops

Demonstrates a secure banking operations network with account lookup, transaction
processing, and compliance checking. Uses sly\_data for authentication tokens.

## Experimental Examples

Research features and advanced architectures.

| Example | Description | Feature |
|:--------|:------------|:--------|
| `agent_network_designer` | Creates agent networks from descriptions | Meta-agent |
| `agent_network_editor` | Modifies existing networks | Meta-agent |
| `experimental/copy_cat` | Clones and runs temporary networks | Reservations |
| `experimental/cruse_agent` | Context-reactive UX | Dynamic UI |
| `experimental/mdap_decomposer` | Recursive problem decomposition | Research |

### agent\_network\_designer

A meta-agent that creates new agent networks from natural language descriptions. Describe
what you want your network to do, and the designer generates the HOCON configuration
automatically.

```
User: "Create an agent network that helps users plan meals based on
       dietary restrictions and available ingredients."

Designer: Creates the HOCON file with appropriate agents and saves it.
```

### copy\_cat

Creates temporary copies of existing agent networks using the Reservations system.
Useful for testing modifications without affecting the original network.

## Next Steps

- [Quick Start](../getting-started/quickstart.md) -- Run your first example
- [Creating Agent Networks](../guides/creating-agent-networks.md) -- Build your own
- [Studio Setup](../getting-started/studio.md) -- Full IDE experience
