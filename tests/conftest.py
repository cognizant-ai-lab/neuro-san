import os
import pytest

# Define known keys
ALL_API_KEYS = [
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "GOOGLE_API_KEY",
]

def get_unexpected_keys(allowed_key):
    """Return a list of other *_API_KEYs that are set and not allowed."""
    return [
        key for key in ALL_API_KEYS
        if key != allowed_key and os.getenv(key)
    ]

@pytest.fixture(autouse=True)
def configure_llm_provider_keys(request, monkeypatch):
    """Ensure only the appropriate LLM provider keys are available for the test being run."""

    is_non_default = request.node.get_closest_marker("non_default_llm_provider")
    is_anthropic = request.node.get_closest_marker("anthropic")
    is_azure = request.node.get_closest_marker("azure")
    is_gemini = request.node.get_closest_marker("gemini")

    if is_non_default:
        if is_anthropic:
            if not os.getenv("ANTHROPIC_API_KEY"):
                pytest.skip("Missing ANTHROPIC_API_KEY for test marked 'anthropic'")
            unexpected = get_unexpected_keys("ANTHROPIC_API_KEY")
            if unexpected:
                pytest.skip(f"Unexpected API keys set: {unexpected} — only ANTHROPIC_API_KEY should be defined.")
                
        elif is_azure:
            if not os.getenv("AZURE_OPENAI_API_KEY"):
                pytest.skip("Missing AZURE_OPENAI_API_KEY for test marked 'azure'")
            unexpected = get_unexpected_keys("AZURE_OPENAI_API_KEY")
            if unexpected:
                pytest.skip(f"Unexpected API keys set: {unexpected} — only AZURE_OPENAI_API_KEY should be defined.")

        elif is_gemini:
            if not os.getenv("GOOGLE_API_KEY"):
                pytest.skip("Missing GOOGLE_API_KEY for test marked 'gemini'")
            unexpected = get_unexpected_keys("GOOGLE_API_KEY")
            if unexpected:
                pytest.skip(f"Unexpected API keys set: {unexpected} — only GOOGLE_API_KEY should be defined.")

        else:
            pytest.skip("Unknown non-default provider; test requires explicit key handling.")
    else:
        # Default: OpenAI
        if not os.getenv("OPENAI_API_KEY"):
            pytest.skip("Missing OPENAI_API_KEY for default LLM test.")
        unexpected = get_unexpected_keys("OPENAI_API_KEY")
        if unexpected:
            pytest.skip(f"Unexpected API keys set: {unexpected} — only OPENAI_API_KEY should be defined.")
