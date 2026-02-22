from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from db import read_query, get_driver
from clustering import ensure_clustered

app = FastAPI(title="ProjectNexus API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/graph")
def get_full_graph(request: Request):
    """Return all nodes and relationships. Auto-runs clustering if any node has no cluster (use ?recluster=1 to force)."""
    force = request.query_params.get("recluster") == "1"
    ensure_clustered(get_driver(), force=force)
    nodes = read_query(
        "MATCH (p:Person) RETURN p.email AS email, p.name AS name, p.cluster AS cluster, p.cluster_name AS cluster_name"
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
        "RETURN DISTINCT p.email AS email, p.name AS name, p.cluster AS cluster, p.cluster_name AS cluster_name",
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
        "MATCH (p:Person) "
        "OPTIONAL MATCH ()-[r:COMMUNICATES_WITH]-() "
        "RETURN count(DISTINCT p) AS node_count, count(DISTINCT r) AS edge_count"
    )
    degrees = read_query(
        "MATCH (p:Person) "
        "OPTIONAL MATCH (p)-[r:COMMUNICATES_WITH]-() "
        "RETURN p.email AS email, p.name AS name, count(r) AS degree "
        "ORDER BY degree DESC"
    )
    return {"counts": counts[0] if counts else {}, "degrees": degrees}
