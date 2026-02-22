"""RAG pipeline using RapidFire AI's RFLangChainRagSpec + OpenRouter."""

from vectorstore import search, get_rag_spec
from llm import complete
from db import read_query

SYSTEM_PROMPT = (
    "You are an analyst for email communication datasets. You have access "
    "to email content, relationship data from a knowledge graph, and document archives. "
    "Use the provided context to answer the user's question accurately. If the context "
    "is insufficient, say so. Cite specific emails, documents, or relationships when possible."
)


def build_context(results: list[dict]) -> str:
    """Format retrieved Pinecone results into a context block for the LLM."""
    parts = []
    for i, r in enumerate(results, 1):
        if r.get("type") == "email":
            parts.append(
                f"[Email {i}] From: {r.get('from', '?')} To: {r.get('to', '?')} "
                f"Subject: {r.get('subject', '?')} Date: {r.get('date', '?')}\n"
                f"{r.get('text', '')}"
            )
        elif r.get("type") == "relationship":
            parts.append(f"[Relationship {i}] {r.get('text', '')}")
        elif r.get("type") == "email_chain":
            parts.append(
                f"[Email Chain {i}] Subject: {r.get('subject', '?')} "
                f"({r.get('n_messages', '?')} messages)\n"
                f"{r.get('text', '')}"
            )
        elif r.get("type") == "epstein_email":
            parts.append(
                f"[Document {i}] Source: {r.get('source_file', '?')} "
                f"Subject: {r.get('subject', '?')} Date: {r.get('date', '?')}\n"
                f"Participants: {r.get('participants', '?')}\n"
                f"Notable figures: {r.get('notable_figures', '?')}\n"
                f"Summary: {r.get('summary', '?')}\n"
                f"{r.get('text', '')}"
            )
        elif r.get("type") == "enron_email":
            parts.append(
                f"[Enron Email {i}] Subject: {r.get('subject', '?')} "
                f"({r.get('n_messages', '?')} messages)\n"
                f"Participants: {r.get('emails', '?')}\n"
                f"{r.get('text', '')}"
            )
        else:
            parts.append(f"[Source {i}] {r.get('text', '')}")
    return "\n\n---\n\n".join(parts)


def query(
    user_question: str,
    model: str | None = None,
    namespaces: list[str] | None = None,
) -> dict:
    """Full RAG pipeline: embed question -> search Pinecone -> build prompt -> LLM."""
    results = search(user_question, namespaces=namespaces)
    context = build_context(results)

    user_prompt = f"Context:\n{context}\n\n---\n\nQuestion: {user_question}"
    answer = complete(SYSTEM_PROMPT, user_prompt, model=model)

    return {
        "answer": answer,
        "sources": [
            {
                "namespace": r.get("namespace"),
                "score": r.get("score"),
                "type": r.get("type"),
                "text_preview": r.get("text", "")[:200],
            }
            for r in results
        ],
        "model": model or "default",
    }


def generate_graph_insights(model: str | None = None) -> dict:
    """Generate overall insights by combining Neo4j stats with Pinecone context."""
    counts = read_query(
        "MATCH (p:Person) "
        "OPTIONAL MATCH ()-[r:COMMUNICATES_WITH]->() "
        "RETURN count(DISTINCT p) AS nodes, count(DISTINCT r) AS edges"
    )
    top_communicators = read_query(
        "MATCH (p:Person)-[r:COMMUNICATES_WITH]-() "
        "RETURN p.name AS name, p.email AS email, count(r) AS degree "
        "ORDER BY degree DESC LIMIT 10"
    )

    rel_results = search(
        "most important communication patterns and relationships",
        namespaces=["relationships"],
        top_k=20,
    )
    context = build_context(rel_results)

    stats = counts[0] if counts else {"nodes": 0, "edges": 0}
    top_list = ", ".join(
        f"{t['name']} ({t['degree']} connections)" for t in top_communicators
    )
    stats_text = (
        f"Graph stats: {stats['nodes']} people, {stats['edges']} relationships.\n"
        f"Top communicators: {top_list}"
    )

    user_prompt = (
        f"Graph statistics:\n{stats_text}\n\n"
        f"Relationship data:\n{context}\n\n"
        "Provide a comprehensive summary of the key communication patterns, "
        "important figures, and notable clusters in this email network."
    )

    answer = complete(SYSTEM_PROMPT, user_prompt, model=model)
    return {
        "answer": answer,
        "stats": stats,
        "top_communicators": top_communicators,
    }
