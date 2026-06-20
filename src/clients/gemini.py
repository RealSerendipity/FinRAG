"""Gemini SDK raw call. Message formatting (role mapping, parts) lives here."""
from __future__ import annotations


def generate(
    messages: list[dict],
    model: str,
    *,
    api_key: str,
    system: str | None,
    temperature: float,
    max_tokens: int,
):
    """Send a generate_content request; return the raw SDK response."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    contents = [
        {
            "role": "model" if m["role"] == "assistant" else m["role"],
            "parts": [{"text": m["content"]}],
        }
        for m in messages
    ]
    cfg = types.GenerateContentConfig(
        system_instruction=system,
        temperature=temperature,
        max_output_tokens=max_tokens,
        # Disable thinking: basic chat doesn't need it, and it breaks low max_tokens budgets.
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    )
    # Wave 5 will add explicit context caching via client.caches.create(...).
    return client.models.generate_content(model=model, contents=contents, config=cfg)


def create_embeddings(
    texts: list[str], *, api_key: str, model: str, task_type: str
) -> list[list[float]]:
    """Embed texts with a Gemini embedding model; return vectors in input order."""
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=api_key)
    resp = client.models.embed_content(
        model=model,
        contents=texts,
        config=types.EmbedContentConfig(task_type=task_type),
    )
    return [e.values for e in resp.embeddings]
