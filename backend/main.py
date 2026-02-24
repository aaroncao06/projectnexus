import os
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI
from pydantic import BaseModel
from typing import List

from config import OPENROUTER_API_KEY, OPENROUTER_MODEL
from db import read_query, get_driver, write_query
from clustering import ensure_clustered
from insights import compute_insights, invalidate_cache as invalidate_insights
from rag import query as rag_query, generate_graph_insights
from typing import Any

app = FastAPI(title="ProjectNexus API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


class QueryRequest(BaseModel):
    question: str
    model: str | None = None
    namespaces: list[str] | None = None


class InsightsRequest(BaseModel):
    model: str | None = None


@app.get("/graph")
def get_full_graph(request: Request):
    """Return all nodes and relationships. Auto-runs clustering if any node has no cluster (use ?recluster=1 to force)."""
    force = request.query_params.get("recluster") == "1"
    if force:
        invalidate_insights()
    ensure_clustered(get_driver(), force=force)
    nodes = read_query(
        "MATCH (p:Person) WHERE (p)-[:COMMUNICATES_WITH]-() "
        "OPTIONAL MATCH (p)-[r:COMMUNICATES_WITH]-() "
        "RETURN p.email AS email, p.name AS name, p.cluster AS cluster, p.cluster_name AS cluster_name, count(r) AS degree"
    )
    edges = read_query(
        "MATCH (a:Person)-[r:COMMUNICATES_WITH]-(b:Person) "
        "WHERE a.email < b.email "
        "RETURN a.email AS source, b.email AS target, properties(r) AS properties"
    )
    return {"nodes": nodes, "edges": edges}


@app.get("/graph/{email}")
def get_subgraph(email: str, depth: int = 1):
    """Return the subgraph around a person up to `depth` hops."""
    depth = max(1, min(depth, 5))  # clamp between 1 and 5
    nodes = read_query(
        f"MATCH (origin:Person {{email: $email}})-[*1..{depth}]-(connected:Person) "
        "WITH collect(DISTINCT connected) + collect(DISTINCT origin) AS people "
        "UNWIND people AS p "
        "OPTIONAL MATCH (p)-[r:COMMUNICATES_WITH]-() "
        "RETURN p.email AS email, p.name AS name, p.cluster AS cluster, p.cluster_name AS cluster_name, count(r) AS degree",
        {"email": email},
    )
    if not nodes:
        raise HTTPException(status_code=404, detail="Person not found")

    emails = [n["email"] for n in nodes]
    edges = read_query(
        "MATCH (a:Person)-[r:COMMUNICATES_WITH]-(b:Person) "
        "WHERE a.email < b.email AND a.email IN $emails AND b.email IN $emails "
        "RETURN a.email AS source, b.email AS target, properties(r) AS properties",
        {"emails": emails},
    )
    return {"nodes": nodes, "edges": edges}


@app.get("/meta")
def get_metadata():
    """Return basic graph stats."""
    counts = read_query(
        "MATCH (p:Person) WHERE (p)-[:COMMUNICATES_WITH]-() "
        "OPTIONAL MATCH (p)-[r:COMMUNICATES_WITH]-(someone) "
        "RETURN count(DISTINCT p) AS node_count, count(DISTINCT r) AS edge_count"
    )
    degrees = read_query(
        "MATCH (p:Person)-[r:COMMUNICATES_WITH]-() "
        "RETURN p.email AS email, p.name AS name, count(r) AS degree "
        "ORDER BY degree DESC"
    )
    return {"counts": counts[0] if counts else {}, "degrees": degrees}


class SummarizeRequest(BaseModel):
    source: str
    target: str


@app.post("/graph/summarize")
def summarize_edge(req: SummarizeRequest):
    """Generate an LLM summary for a specific edge on-demand."""
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="OPENROUTER_API_KEY not set")

    # 1. Fetch comments
    results = read_query(
        "MATCH (a:Person {email: $source})-[r:COMMUNICATES_WITH]-(b:Person {email: $target}) "
        "RETURN r.comments AS comments",
        {"source": req.source, "target": req.target}
    )
    if not results or not results[0].get("comments"):
        raise HTTPException(status_code=404, detail="No comments found for this relationship")

    comments = results[0]["comments"]
    comment_text = "\n".join(f"- {c}" for c in comments)

    # 2. Call LLM
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=OPENROUTER_API_KEY,
    )
    prompt = (
        f"Below are observations about the relationship between "
        f"{req.source} and {req.target}:\n\n"
        f"{comment_text}\n\n"
        f"Write a 1-2 sentence summary of their overall relationship."
    )

    try:
        response = client.chat.completions.create(
            model=OPENROUTER_MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
        summary = (response.choices[0].message.content or "").strip()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM call failed: {str(e)}")

    # 3. Save summary
    write_query(
        "MATCH (a:Person {email: $source})-[r:COMMUNICATES_WITH]-(b:Person {email: $target}) "
        "SET r.summary = $summary",
        {"source": req.source, "target": req.target, "summary": summary}
    )

    return {"summary": summary}


@app.get("/insights")
def get_insights():
    """Return anomaly detection and graph analysis insights."""
    driver = get_driver()
    ensure_clustered(driver)  # make sure clusters exist first
    return {"insights": compute_insights(driver)}


def _handle_pinecone_error(e: Exception) -> None:
    """Raise HTTPException with a clear message for Pinecone index-not-found."""
    if "NotFound" in type(e).__name__ or "not found" in str(e).lower():
        from config import PINECONE_INDEX_NAME
        raise HTTPException(
            status_code=503,
            detail=(
                f"Pinecone index '{PINECONE_INDEX_NAME}' not found. "
                "Create it in the Pinecone console (dimension 384, cosine metric) or run the agent index scripts first."
            ),
        )
    raise


@app.post("/query")
def post_query(req: QueryRequest):
    """RAG query: embed question, search Pinecone, generate answer via OpenRouter."""
    try:
        result = rag_query(req.question, model=req.model, namespaces=req.namespaces)
        return result
    except HTTPException:
        raise
    except Exception as e:
        _handle_pinecone_error(e)


@app.post("/debug/rag")
def debug_rag(req: QueryRequest):
    """Debug endpoint: return raw retrieved documents and the context built for the LLM.

    Useful to inspect what the retriever returns for a question/namespaces without
    invoking the LLM generation.
    """
    try:
        # Import here to avoid circular imports in module init
        from vectorstore import search

        results = search(req.question, namespaces=req.namespaces, top_k=10)
        return {"n_results": len(results), "results": results}
    except Exception as e:
        _handle_pinecone_error(e)


@app.post("/insights")
def post_insights(req: InsightsRequest):
    """Generate overall graph insights using the LLM."""
    try:
        result = generate_graph_insights(model=req.model)
        return result
    except HTTPException:
        raise
    except Exception as e:
        _handle_pinecone_error(e)


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
