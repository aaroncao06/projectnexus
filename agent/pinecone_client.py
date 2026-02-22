"""Pinecone index initialization and upsert operations."""

from pinecone import Pinecone, ServerlessSpec
from config import PINECONE_API_KEY, PINECONE_INDEX_NAME, EMBEDDING_DIMENSION

_index = None


def get_index():
    """Return a Pinecone Index handle, creating the index if it doesn't exist."""
    global _index
    if _index is None:
        pc = Pinecone(api_key=PINECONE_API_KEY)
        existing = [idx.name for idx in pc.list_indexes()]
        if PINECONE_INDEX_NAME not in existing:
            pc.create_index(
                name=PINECONE_INDEX_NAME,
                dimension=EMBEDDING_DIMENSION,
                metric="cosine",
                spec=ServerlessSpec(cloud="aws", region="us-east-1"),
            )
        _index = pc.Index(PINECONE_INDEX_NAME)
    return _index


def upsert_vectors(vectors: list[dict], namespace: str):
    """Upsert vectors to Pinecone in batches of 100.

    Each vector should be {"id": str, "values": list[float], "metadata": dict}.
    """
    index = get_index()
    for i in range(0, len(vectors), 100):
        batch = vectors[i : i + 100]
        index.upsert(vectors=batch, namespace=namespace)
