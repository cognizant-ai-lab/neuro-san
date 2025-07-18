import os
import pytest


@pytest.fixture(autouse=True)
def configure_llm_provider_keys(request, monkeypatch):
    """Ensure only the appropriate LLM provider keys are available for the test being run."""

    is_non_default = request.node.get_closest_marker("non_default_llm_provider")
    is_anthropic = request.node.get_closest_marker("anthropic")
    is_azure = request.node.get_closest_marker("azure")
    is_gemini = request.node.get_closest_marker("gemini")
    is_ollama = request.node.get_closest_marker("ollama")

    if is_non_default:
        # For any non-default provider: clear OPENAI key to prevent accidental use
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        if is_anthropic:
            if not os.getenv("ANTHROPIC_API_KEY"):
                pytest.skip("Missing ANTHROPIC_API_KEY for test marked 'anthropic'")
        elif is_azure:
            if not os.getenv("AZURE_OPENAI_API_KEY"):
                pytest.skip("Missing AZURE_OPENAI_API_KEY for test marked 'azure'")
        elif is_gemini:
            if not os.getenv("GOOGLE_API_KEY"):
                pytest.skip("Missing GOOGLE_API_KEY for test marked 'gemini'")
        elif is_ollama:
            print("No key needed for test marked 'ollama'")
        else:
            pytest.skip("Unknown non-default provider; test requires explicit key handling.")
    else:
        # Default case: assume OpenAI is used
        if not os.getenv("OPENAI_API_KEY"):
            pytest.skip("Missing OPENAI_API_KEY for default LLM test.")
