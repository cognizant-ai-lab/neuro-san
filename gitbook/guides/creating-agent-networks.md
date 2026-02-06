# Creating Agent Networks

This guide walks you through designing and building multi-agent networks, from simple
single-agent setups to complex hierarchies with specialized delegation.

## Planning Your Network

Before writing HOCON, sketch out the agents you need:

1. **What is the user trying to do?** This defines your Front Man's description.
2. **What subtasks are involved?** Each becomes a potential sub-agent.
3. **Do any subtasks need external data or actions?** These need CodedTools or toolbox tools.
4. **How should agents communicate?** Decide on delegation patterns.

## Single-Agent Network

The simplest network has one agent that handles everything:

```hocon
{
    "llm_config": {
        "model_name": "gpt-4o"
    },
    "tools": [
        {
            "name": "recipe_assistant",
            "function": {
                "description": "I help you find and create recipes
                    based on ingredients you have available."
            },
            "instructions": "You are a cooking assistant.
                When the user tells you what ingredients they have,
                suggest recipes they can make.
                Always include estimated cooking time and difficulty level."
        }
    ]
}
```

This works well for tasks that a single LLM can handle without external data or
specialized reasoning.

## Two-Agent Network

Add a sub-agent when you need specialization:

```hocon
{
    "llm_config": {
        "model_name": "gpt-4o"
    },
    "tools": [
        {
            "name": "recipe_assistant",
            "function": {
                "description": "I help you find recipes and calculate
                    nutritional information."
            },
            "instructions": "You are a cooking assistant.
                Suggest recipes based on the user's ingredients.
                When the user asks about nutrition, delegate to
                the nutrition_calculator.",
            "tools": ["nutrition_calculator"]
        },
        {
            "name": "nutrition_calculator",
            "function": {
                "description": "Calculates nutritional information for recipes.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "recipe": {
                            "type": "string",
                            "description": "The recipe to analyze."
                        }
                    },
                    "required": ["recipe"]
                }
            },
            "instructions": "You are a nutrition specialist.
                Calculate calories, protein, carbs, and fat for the given recipe.
                Be precise and cite standard nutritional databases."
        }
    ]
}
```

The Front Man (recipe\_assistant) handles general requests and delegates nutrition
questions to the specialist.

## Branching Network

When multiple specialists exist at the same level, the Front Man chooses between them:

```hocon
{
    "llm_config": {
        "model_name": "gpt-4o"
    },
    "tools": [
        {
            "name": "travel_planner",
            "function": {
                "description": "I help plan trips including flights,
                    hotels, and activities."
            },
            "instructions": "You are a travel planning assistant.
                Delegate flight questions to the flight_agent,
                hotel questions to the hotel_agent,
                and activity questions to the activity_agent.
                Combine their responses into a cohesive travel plan.",
            "tools": ["flight_agent", "hotel_agent", "activity_agent"]
        },
        {
            "name": "flight_agent",
            "function": {
                "description": "Helps find and compare flights.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "origin": {
                            "type": "string",
                            "description": "Departure city."
                        },
                        "destination": {
                            "type": "string",
                            "description": "Arrival city."
                        },
                        "date": {
                            "type": "string",
                            "description": "Travel date."
                        }
                    },
                    "required": ["origin", "destination"]
                }
            },
            "instructions": "You are a flight specialist.
                Suggest flight options with approximate prices and durations."
        },
        {
            "name": "hotel_agent",
            "function": {
                "description": "Helps find and compare hotels.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {
                            "type": "string",
                            "description": "City to find hotels in."
                        },
                        "budget": {
                            "type": "string",
                            "description": "Budget range."
                        }
                    },
                    "required": ["city"]
                }
            },
            "instructions": "You are a hotel specialist.
                Suggest hotel options based on location and budget."
        },
        {
            "name": "activity_agent",
            "function": {
                "description": "Suggests activities and attractions.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "city": {
                            "type": "string",
                            "description": "City to find activities in."
                        },
                        "interests": {
                            "type": "string",
                            "description": "User's interests."
                        }
                    },
                    "required": ["city"]
                }
            },
            "instructions": "You are an activities specialist.
                Suggest local attractions, restaurants, and experiences."
        }
    ]
}
```

## Deep Hierarchy

Sub-agents can have their own sub-agents, creating deeper hierarchies:

```hocon
{
    "llm_config": {
        "model_name": "gpt-4o"
    },
    "tools": [
        {
            "name": "customer_service",
            "function": {
                "description": "I handle customer service inquiries
                    for billing, technical support, and account management."
            },
            "instructions": "Route customer inquiries to the
                appropriate department.",
            "tools": ["billing_dept", "tech_support"]
        },
        {
            "name": "billing_dept",
            "function": {
                "description": "Handles billing and payment inquiries.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "inquiry": {
                            "type": "string",
                            "description": "The billing inquiry."
                        }
                    },
                    "required": ["inquiry"]
                }
            },
            "instructions": "Handle billing inquiries.
                For refunds, use the refund_processor.
                For invoice questions, answer directly.",
            "tools": ["refund_processor"]
        },
        {
            "name": "tech_support",
            "function": {
                "description": "Handles technical support issues.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "issue": {
                            "type": "string",
                            "description": "The technical issue."
                        }
                    },
                    "required": ["issue"]
                }
            },
            "instructions": "Troubleshoot technical issues step by step."
        },
        {
            "name": "refund_processor",
            "function": {
                "description": "Processes refund requests.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "reason": {
                            "type": "string",
                            "description": "Reason for the refund."
                        },
                        "amount": {
                            "type": "string",
                            "description": "Refund amount."
                        }
                    },
                    "required": ["reason"]
                }
            },
            "instructions": "Process refund requests.
                Verify the reason is valid and calculate the refund amount."
        }
    ]
}
```

This creates:

```
customer_service (Front Man)
├── billing_dept
│   └── refund_processor
└── tech_support
```

## Using AAOSA for Dynamic Routing

When agents have overlapping domains, use the AAOSA protocol to let agents self-select:

```hocon
{
    "commondefs": {
        "replacement_strings": {
            "aaosa_instructions": """
                When you receive an inquiry:
                0. If this is clearly not your area, say so immediately.
                1. If there is any chance it is relevant, call ALL your
                   tools before declaring irrelevance.
                2. Based on what your tools return, provide an answer
                   or declare that you are not the right agent.
            """
        }
    },
    "llm_config": {
        "model_name": "gpt-4o"
    },
    "tools": [
        {
            "name": "support_router",
            "function": {
                "description": "I help with product questions."
            },
            "instructions": "You route product questions.
                {aaosa_instructions}",
            "tools": ["hardware_expert", "software_expert", "warranty_agent"]
        },
        {
            "name": "hardware_expert",
            "function": {
                "description": "Answers hardware-related questions.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "The hardware question."
                        }
                    },
                    "required": ["question"]
                }
            },
            "instructions": "{aaosa_instructions}
                You specialize in hardware components and specifications."
        },
        {
            "name": "software_expert",
            "function": {
                "description": "Answers software-related questions.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "The software question."
                        }
                    },
                    "required": ["question"]
                }
            },
            "instructions": "{aaosa_instructions}
                You specialize in software, drivers, and firmware."
        },
        {
            "name": "warranty_agent",
            "function": {
                "description": "Handles warranty inquiries.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "The warranty question."
                        }
                    },
                    "required": ["question"]
                }
            },
            "instructions": "{aaosa_instructions}
                You handle warranty claims and coverage questions."
        }
    ]
}
```

## Best Practices

1. **Keep agents focused.** Each agent should have a clear, narrow responsibility.
2. **Write clear function descriptions.** The LLM uses these to decide when to call an agent.
3. **Define parameters explicitly.** Specify required parameters so the LLM knows what
   information to extract from the user.
4. **Use commondefs for reuse.** Avoid duplicating instructions across agents.
5. **Test incrementally.** Start with a simple network and add agents one at a time.
6. **Use AAOSA when domains overlap.** Let agents self-select rather than hard-coding routing.

## Next Steps

- [Configuring LLMs](configuring-llms.md) -- Use different models for different agents
- [Writing CodedTools](coded-tools.md) -- Add real-world capabilities
- [Examples](../examples/README.md) -- See complete, working networks
