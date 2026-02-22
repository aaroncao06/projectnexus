"""Multi-namespace Pinecone retriever using RapidFire AI + LangChain."""

import os
from typing import Any

from collections.abc import Iterator

from langchain_core.callbacks import CallbackManagerForRetrieverRun
from langchain_core.document_loaders import BaseLoader
from langchain_core.documents import Document
from langchain_core.retrievers import BaseRetriever
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_pinecone import PineconeVectorStore
from langchain_text_splitters import CharacterTextSplitter
from rapidfireai.automl import RFLangChainRagSpec

from config import (
    DEFAULT_NAMESPACES,
    EMBEDDING_MODEL,
    PINECONE_API_KEY,
    PINECONE_INDEX_NAME,
    RAG_TOP_K,
)

class _NoOpLoader(BaseLoader):
    """No-op document loader for pre-indexed data."""

    def lazy_load(self) -> Iterator[Document]:
        return iter([])


# langchain-pinecone reads PINECONE_API_KEY from env
os.environ.setdefault("PINECONE_API_KEY", PINECONE_API_KEY)

_embeddings = None


def get_embeddings() -> HuggingFaceEmbeddings:
    global _embeddings
    if _embeddings is None:
        _embeddings = HuggingFaceEmbeddings(
            model_name=f"sentence-transformers/{EMBEDDING_MODEL}",
            model_kwargs={"device": "cpu"},
            encode_kwargs={"normalize_embeddings": True},
        )
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
    """Return an RFLangChainRagSpec backed by the multi-namespace retriever. Requires rapidfireai."""
    from rapidfireai.automl import RFLangChainRagSpec

    retriever = get_retriever(namespaces=namespaces, top_k=top_k)
    return RFLangChainRagSpec(
        document_loader=_NoOpLoader(),
        text_splitter=CharacterTextSplitter(chunk_size=1000, chunk_overlap=0),
        embedding_cls=HuggingFaceEmbeddings,
        embedding_kwargs={
            "model_name": f"sentence-transformers/{EMBEDDING_MODEL}",
            "model_kwargs": {"device": "cpu"},
            "encode_kwargs": {"normalize_embeddings": True},
        },
        retriever=retriever,
        search_type="similarity",
        search_kwargs={"k": top_k or RAG_TOP_K},
    )


def search(
    query: str,
    namespaces: list[str] | None = None,
    top_k: int | None = None,
) -> list[dict]:
    """Search Pinecone across namespaces. Returns metadata dicts with score.

    Backward-compatible interface used by rag.py.
    """
    retriever = get_retriever(namespaces=namespaces, top_k=top_k)
    docs = retriever.invoke(query)
    return [
        {"score": d.metadata.get("score", 0.0), **d.metadata, "text": d.page_content}
        for d in docs
    ]
