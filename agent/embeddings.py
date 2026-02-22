"""Embedding helpers using all-MiniLM-L6-v2 (local, free, fast)."""

from email.parser import Parser
from sentence_transformers import SentenceTransformer
from config import EMBEDDING_MODEL

_model = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        print(f"Loading embedding model: {EMBEDDING_MODEL} ...")
        _model = SentenceTransformer(EMBEDDING_MODEL)
        print("Model loaded.")
    return _model


def embed_texts(texts: list[str], batch_size: int = 256) -> list[list[float]]:
    """Embed a batch of texts locally."""
    model = get_model()
    embeddings = model.encode(
        texts,
        batch_size=batch_size,
        show_progress_bar=False,
        normalize_embeddings=True,
    )
    return embeddings.tolist()


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
