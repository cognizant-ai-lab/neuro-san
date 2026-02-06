# Data-Driven Tests

Neuro SAN supports data-driven testing where test cases are defined in HOCON files rather
than Python code. This makes it easy for non-programmers to write and maintain tests.

## How It Works

1. Define test cases in HOCON files under `tests/fixtures/`
2. The `DynamicHoconUnitTests` class discovers these files automatically
3. Each HOCON file generates one or more pytest test methods
4. Tests run the agent network and validate responses

## Writing a Test Case

Create a HOCON file in the appropriate fixtures directory:

```
tests/fixtures/basic/hello_world/test_hello_world.hocon
```

```hocon
{
    "agent": "basic/hello_world",
    "timeout_in_seconds": 120,
    "success_ratio": "1/1",
    "interactions": [
        {
            "text": "From earth, greet the planet Mars with a short message.",
            "response": {
                "text": {
                    "gist": [
                        "The response contains a greeting directed at Mars.",
                        "The greeting is brief, approximately two words."
                    ],
                    "not_gist": [
                        "The response asks for more information.",
                        "The response refuses to provide a greeting."
                    ]
                }
            }
        }
    ]
}
```

## Gist Validation

The `gist` field is the most powerful validation mechanism. Instead of matching exact
strings (which would be brittle given LLM non-determinism), it uses an LLM discriminator
to evaluate whether the response satisfies each semantic criterion.

### How Gist Works

Each gist statement is evaluated independently by a discriminator LLM:

```hocon
"gist": [
    "The response recommends at least one Italian restaurant.",
    "The response includes approximate price ranges.",
    "The response mentions the restaurant's location."
]
```

All `gist` statements must pass. All `not_gist` statements must fail.

### Writing Good Gist Statements

- Be specific about what you expect
- Focus on semantics, not exact wording
- Use positive statements for `gist` (what should be present)
- Use negative statements for `not_gist` (what should be absent)
- Avoid overly strict criteria that depend on exact phrasing

## Multi-Turn Tests

Test conversations with multiple exchanges:

```hocon
{
    "agent": "basic/trip_planner",
    "interactions": [
        {
            "text": "I want to plan a trip to Paris.",
            "response": {
                "text": {
                    "gist": ["Acknowledges the trip to Paris."]
                }
            }
        },
        {
            "text": "What hotels do you recommend?",
            "response": {
                "text": {
                    "gist": [
                        "Recommends hotels in Paris.",
                        "References the trip context from the previous message."
                    ]
                }
            }
        }
    ]
}
```

## Tests with sly\_data

Inject context via sly\_data:

```hocon
{
    "agent": "basic/coffee_finder_advanced",
    "interactions": [
        {
            "sly_data": {
                "time": "8 am",
                "location": "office building"
            },
            "text": "Where can I get coffee?",
            "response": {
                "text": {
                    "gist": [
                        "Suggests a coffee option appropriate for an office setting.",
                        "The suggestion is relevant for early morning."
                    ]
                }
            }
        }
    ]
}
```

## Stock Validators

In addition to gist, you can use deterministic validators:

### Exact Match

```hocon
"response": {
    "text": {
        "value": "Hello, Mars!"
    }
}
```

### Keywords

```hocon
"response": {
    "text": {
        "keywords": ["weather", "temperature"],
        "not_keywords": ["error", "sorry"]
    }
}
```

### Length Constraints

```hocon
"response": {
    "text": {
        "less": 500,
        "greater": 10
    }
}
```

## Handling Non-Determinism

LLM responses vary between runs. Use `success_ratio` to account for this:

```hocon
{
    "success_ratio": "4/5"
}
```

This runs the test 5 times and requires at least 4 passes. Use this for tests where
occasional variation in LLM output is acceptable.

## Next Steps

- [Test Case HOCON Reference](../reference/test-case-hocon.md) -- Complete field reference
- [Running Tests](running-tests.md) -- How to execute tests
- [HOCON Validation](hocon-validation.md) -- Validate configuration files
