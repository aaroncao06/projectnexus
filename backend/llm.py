"""OpenRouter LLM client using the OpenAI-compatible API."""

from openai import OpenAI
from config import OPENROUTER_API_KEY, OPENROUTER_BASE_URL, OPENROUTER_MODEL

_client = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=OPENROUTER_API_KEY,
            base_url=OPENROUTER_BASE_URL,
        )
    return _client


def complete(system_prompt: str, user_prompt: str, model: str | None = None) -> str:
    """Send a chat completion request via OpenRouter."""
    client = get_client()
    response = client.chat.completions.create(
        model=model or OPENROUTER_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )
    return response.choices[0].message.content
