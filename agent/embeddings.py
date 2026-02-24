"""Embedding helpers using OpenAI embeddings (remote).

This replaces the local SentenceTransformer-based embedding to avoid
heavy CPU/GPU dependencies (sentence-transformers, torch). It uses the
OpenAI Python client to create embeddings via the model configured in
`EMBEDDING_MODEL` in `agent.config`.

The public functions keep the same signatures: `embed_texts(texts, batch_size)`
and `chunk_email(raw_message)`. This lets the rest of the code remain
unchanged while switching to OpenAI-hosted embeddings.
"""

from email.parser import Parser
from typing import List
from openai import OpenAI
from config import EMBEDDING_MODEL
import os
import math

# Create an OpenAI client. Prefer OPENAI_API_KEY, fallback to OPENROUTER_API_KEY.
def _make_client() -> OpenAI:
    # Prefer OpenRouter key if present, otherwise fall back to OpenAI key
    api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
    openrouter_base = os.getenv("OPENROUTER_BASE_URL")
    # If no explicit base URL but an OpenRouter key exists, use default OpenRouter base
    if not openrouter_base and os.getenv("OPENROUTER_API_KEY"):
        openrouter_base = "https://openrouter.ai/api/v1"
    if openrouter_base:
        return OpenAI(base_url=openrouter_base, api_key=api_key)
    return OpenAI(api_key=api_key)


_client = _make_client()


def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm == 0:
        return vec
    return [x / norm for x in vec]


def embed_texts(texts: list[str], batch_size: int = 256) -> list[list[float]]:
    """Embed a batch of texts using OpenAI embeddings.

    Returns a list of embedding vectors (floats). The function sends the
    texts to the embeddings endpoint in chunks of `batch_size` to avoid
    overly large requests.
    """
    embeddings: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        resp = _client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
        # resp.data is a list of {'embedding': [...]} matching order
        for item in resp.data:
            vec = item.embedding
            # normalize to mimic previous behavior (normalize_embeddings=True)
            embeddings.append(_normalize(vec))
    return embeddings


def chunk_email(raw_message: str, max_chars: int = 1000) -> list[dict]:
    """Parse a raw email message and return chunks with metadata.

    Each chunk is a dict with keys: text, from, to, subject, date.
    Long bodies are split into overlapping windows.
    """
    parser = Parser()
    msg = parser.parsestr(raw_message)

    sender = msg.get("From", "")
    to = msg.get("To", "")
    subject = msg.get("Subject", "")
    date = msg.get("Date", "")

    body = msg.get_payload()
    if not isinstance(body, str):
        body = ""
    body = body.strip()

    header_line = f"From: {sender} | To: {to} | Subject: {subject} | Date: {date}"

    if not body:
        return [{"text": header_line, "from": sender, "to": to, "subject": subject, "date": date}]

    chunks = []
    if len(body) <= max_chars:
        chunks.append(f"{header_line}\n\n{body}")
    else:
        stride = max_chars // 2
        for start in range(0, len(body), stride):
            segment = body[start : start + max_chars]
            chunks.append(f"{header_line}\n\n{segment}")
            if start + max_chars >= len(body):
                break

    return [
        {"text": chunk, "from": sender, "to": to, "subject": subject, "date": date}
        for chunk in chunks
    ]
