import os
import pytest


@pytest.fixture(autouse=True)
def configure_llm_provider_keys(request, monkeypatch):
    """Ensure only the appropriate LLM provider keys are available for the test being run."""

    is_non_default = request.node.get_closest_marker("non_default_llm_provider")
    is_anthropic = request.node.get_closest_marker("anthropic")
    is_gemini = request.node.get_closest_marker("gemini")

    if is_non_default:
        # For any non-default provider: clear OPENAI key to prevent accidental use
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        if is_anthropic:
            if not os.getenv("ANTHROPIC_API_KEY"):
                pytest.skip("Missing ANTHROPIC_API_KEY for test marked 'anthropic'")
        elif is_gemini:
            if not os.getenv("GOOGLE_API_KEY"):
                pytest.skip("Missing AGOOGLE_API_KEY for test marked 'anthropic'")
        else:
            pytest.skip("Unknown non-default provider; test requires explicit key handling.")
    else:
        # Default case: assume OpenAI is used
        if not os.getenv("OPENAI_API_KEY"):
            pytest.skip("Missing OPENAI_API_KEY for default LLM test.")
