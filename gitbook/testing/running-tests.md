# Running Tests

Neuro SAN uses pytest with custom markers to organize tests by type and scope.

## Test Categories

| Marker | Description | Requires Server | Requires API Key |
|:-------|:------------|:----------------|:-----------------|
| Basic unit tests | Standard Python unit tests | No | No |
| `needs_server` | Tests that require a running server | Yes | Varies |
| `integration` | Full integration tests | Yes | Yes |
| `smoke` | Smoke tests across LLM providers | No | Yes |

## Running Tests

### All Tests

```bash
pytest
```

### Basic Unit Tests Only

Run tests that don't need a server or API keys:

```bash
pytest -m "not needs_server and not integration and not smoke"
```

### Integration Tests

Start the server first, then run integration tests:

```bash
# Terminal 1: Start server
python -m neuro_san.service.main_loop.server_main_loop

# Terminal 2: Run tests
pytest -m integration
```

### Smoke Tests

Smoke tests validate agent networks across different LLM providers:

```bash
pytest -m smoke
```

Run for a specific provider:

```bash
pytest -m "smoke and openai"
pytest -m "smoke and anthropic"
pytest -m "smoke and gemini"
```

### Neuro SAN Studio Tests

In the Studio repository:

```bash
# All tests
make test

# Integration tests
make test-integration

# Specific markers
pytest -m integration_basic
pytest -m integration_industry_airline_policy
```

## Verbose Output

```bash
pytest --verbose --capture=no -m smoke
```

## Debugging Tests

Use `pytest.set_trace()` for interactive debugging:

```python
def test_my_agent():
    import pytest
    pytest.set_trace()
    # Your test code
```

Or use the `--pdb` flag to drop into the debugger on failures:

```bash
pytest --pdb -m integration
```

## CI/CD Integration

Neuro SAN uses GitHub Actions for automated testing. The smoke test workflow runs daily
against multiple LLM providers:

- OpenAI (GPT-4o)
- Anthropic (Claude)
- Google Gemini
- Azure OpenAI
- Amazon Bedrock
- Ollama (local)

See `.github/workflows/smoke.yml` for the workflow configuration.

## Next Steps

- [Data-Driven Tests](data-driven-tests.md) -- Write HOCON-based test cases
- [HOCON Validation](hocon-validation.md) -- Validate configuration files
