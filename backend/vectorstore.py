"""Multi-namespace Pinecone retriever using LangChain + OpenAI embeddings."""

import os
from typing import Any

from collections.abc import Iterator

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.document_loaders import BaseLoader
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from openai import OpenAI
from langchain_pinecone import PineconeVectorStore

from config import (
    DEFAULT_NAMESPACES,
    EMBEDDING_MODEL,
    PINECONE_API_KEY,
    PINECONE_INDEX_NAME,
    RAG_TOP_K,
)

class _NoOpLoader(BaseLoader):
    """No-op document loader for pre-indexed data (kept for API compatibility)."""

    def lazy_load(self) -> Iterator[Document]:
        return iter([])


# langchain-pinecone reads PINECONE_API_KEY from env
os.environ.setdefault("PINECONE_API_KEY", PINECONE_API_KEY)

_embeddings = None


class OpenAIEmbeddingsWrapper:
    """Thin wrapper exposing the methods expected by LangChain/Pinecone stores.

    Provides `embed_documents` and `embed_query` which call the OpenAI
    embeddings endpoint. The wrapper normalizes vectors to unit length to
    preserve previous behaviour.
    """

    def __init__(self, model_name: str):
        # Create OpenAI client with either OPENAI_API_KEY or OPENROUTER_API_KEY.
        import os

        # Prefer OpenRouter key if present, otherwise fall back to OpenAI key
        api_key = os.getenv("OPENROUTER_API_KEY") or os.getenv("OPENAI_API_KEY")
        base_url = os.getenv("OPENROUTER_BASE_URL")
        if not base_url and os.getenv("OPENROUTER_API_KEY"):
            base_url = "https://openrouter.ai/api/v1"
        if base_url:
            self._client = OpenAI(base_url=base_url, api_key=api_key)
        else:
            self._client = OpenAI(api_key=api_key)
        self.model_name = model_name

    def _normalize(self, vec: list[float]) -> list[float]:
        s = sum(x * x for x in vec)
        if s <= 0:
            return vec
        norm = s ** 0.5
        return [x / norm for x in vec]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        resp = self._client.embeddings.create(model=self.model_name, input=texts)
        return [self._normalize(item.embedding) for item in resp.data]

    def embed_query(self, text: str) -> list[float]:
        resp = self._client.embeddings.create(model=self.model_name, input=[text])
        return self._normalize(resp.data[0].embedding)


def get_embeddings() -> OpenAIEmbeddingsWrapper:
    global _embeddings
    if _embeddings is None:
        _embeddings = OpenAIEmbeddingsWrapper(model_name=EMBEDDING_MODEL)
    return _embeddings


def _build_store(namespace: str) -> PineconeVectorStore:
    return PineconeVectorStore(
        index_name=PINECONE_INDEX_NAME,
        embedding=get_embeddings(),
        namespace=namespace,
        text_key="text",
    )


class MultiNamespaceRetriever(BaseRetriever):
    """Retriever that searches multiple Pinecone namespaces and merges results."""

    namespaces: list[str] = DEFAULT_NAMESPACES
    top_k: int = RAG_TOP_K
    _stores: dict[str, Any] = {}

    class Config:
        arbitrary_types_allowed = True

    def _get_relevant_documents(
        self, query: str, *, run_manager: CallbackManagerForRetrieverRun
    ) -> list[Document]:
        all_results: list[tuple[Document, float]] = []
        for ns in self.namespaces:
            if ns not in self._stores:
                self._stores[ns] = _build_store(ns)
            store = self._stores[ns]
            try:
                results = store.similarity_search_with_score(query, k=self.top_k)
            except Exception:
                continue
            for doc, score in results:
                doc.metadata["namespace"] = ns
                doc.metadata["score"] = score
                all_results.append((doc, score))

        all_results.sort(key=lambda x: x[1], reverse=True)
        return [doc for doc, _ in all_results[: self.top_k]]


def get_retriever(
    namespaces: list[str] | None = None,
    top_k: int | None = None,
) -> MultiNamespaceRetriever:
    return MultiNamespaceRetriever(
        namespaces=namespaces or DEFAULT_NAMESPACES,
        top_k=top_k or RAG_TOP_K,
    )


def get_rag_spec(
    namespaces: list[str] | None = None,
    top_k: int | None = None,
):
    """Placeholder for the old rapidfireai-based RAG spec.

    rapidfireai (and thus PyTorch) has been removed from the deployment
    to keep the Vercel Lambda bundle small. This helper is left as a stub
    so that any legacy imports fail with a clear message if called.
    """
    raise RuntimeError(
        "get_rag_spec is not available in this deployment because it depended on "
        "rapidfireai/PyTorch, which were removed to keep the serverless bundle small. "
        "Use the `search` helper with your own LangChain pipeline instead."
    )


def search(
    query: str,
    namespaces: list[str] | None = None,
    top_k: int | None = None,
) -> list[dict]:
    """Search Pinecone across namespaces. Returns metadata dicts with score.

    Backward-compatible interface used by rag.py.
    """
    print(f"vectorstore.search called: query={query!r} namespaces={namespaces} top_k={top_k}")
    retriever = get_retriever(namespaces=namespaces, top_k=top_k)
    docs = retriever.invoke(query)
    print(f"vectorstore: retriever returned {len(docs)} documents")
    return [
        {"score": d.metadata.get("score", 0.0), **d.metadata, "text": d.page_content}
        for d in docs
    ]
