"""
Graph clustering using K-Means and Louvain community detection.

Pulls graph data from Neo4j, computes clusters, assigns a category name per cluster,
and writes `cluster` and `cluster_name` back onto each Person node.

Usage:
    python clustering.py kmeans [n]       # K-Means, default n=4
    python clustering.py louvain          # Louvain (k automatic)
    python clustering.py kmeans 5 --llm   # K-Means with LLM-generated cluster names (needs OPENROUTER_API_KEY)
"""

import os
import sys
import threading
import numpy as np
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
import networkx as nx
from community import community_louvain  # python-louvain

from neo4j import GraphDatabase
from config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, OPENROUTER_API_KEY


def get_driver():
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


def fetch_graph_data(driver):
    """Pull all nodes and edges from Neo4j."""
    with driver.session() as session:
        nodes = session.run(
            "MATCH (p:Person) RETURN p.email AS email, p.name AS name"
        ).data()

        edges = session.run(
            "MATCH (a:Person)-[r:COMMUNICATES_WITH]-(b:Person) "
            "WHERE a.email < b.email "
            "RETURN a.email AS source, b.email AS target, "
            "       coalesce(r.email_count, 1) AS weight"
        ).data()

    return nodes, edges


def build_networkx_graph(nodes, edges):
    """Build a NetworkX graph from Neo4j data."""
    G = nx.Graph()
    for node in nodes:
        G.add_node(node["email"], name=node["name"])
    for edge in edges:
        G.add_edge(edge["source"], edge["target"], weight=edge["weight"])
    return G


def build_feature_matrix(G):
    """
    Build a feature vector for each node based on graph properties:
      - degree (number of connections)
      - weighted degree (sum of email counts)
      - clustering coefficient
      - average neighbor degree
      - betweenness centrality
    """
    emails = list(G.nodes())

    degree = dict(G.degree())
    weighted_degree = dict(G.degree(weight="weight"))
    clustering_coeff = nx.clustering(G)
    avg_neighbor_deg = nx.average_neighbor_degree(G)
    betweenness = nx.betweenness_centrality(G)

    features = []
    for email in emails:
        features.append([
            degree.get(email, 0),
            weighted_degree.get(email, 0),
            clustering_coeff.get(email, 0),
            avg_neighbor_deg.get(email, 0),
            betweenness.get(email, 0),
        ])

    return emails, np.array(features)


def run_kmeans(driver, n_clusters=4, use_llm=False):
    """Run K-Means clustering, assign category names, and write back to Neo4j."""
    print(f"Running K-Means clustering (k={n_clusters})...")

    nodes, edges = fetch_graph_data(driver)
    G = build_networkx_graph(nodes, edges)
    emails, X = build_feature_matrix(G)

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    k = min(n_clusters, len(emails))
    kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
    labels = kmeans.fit_predict(X_scaled)

    # Assign category names (LLM if requested and available, else rule-based)
    cluster_names = None
    if use_llm:
        cluster_names = assign_cluster_names_llm(emails, labels.tolist(), G)
    if cluster_names is None:
        cluster_names = assign_cluster_names_rule(G, emails, labels.tolist())
    write_clusters(driver, emails, labels.tolist(), cluster_names)

    print(f"\nK-Means clustering complete ({k} clusters):\n")
    for cluster_id in range(k):
        name = cluster_names[cluster_id] if cluster_id < len(cluster_names) else f"Cluster {cluster_id}"
        members = [emails[i] for i, l in enumerate(labels) if l == cluster_id]
        member_names = [str(G.nodes[e].get("name") or e) for e in members]
        print(f"  {name}: {', '.join(member_names)}")

    return dict(zip(emails, [int(l) for l in labels]))


def run_louvain(driver, use_llm=False, silent=False):
    """Run Louvain community detection, assign category names, and write back to Neo4j."""
    if not silent:
        print("Running Louvain community detection...")

    nodes, edges = fetch_graph_data(driver)
    G = build_networkx_graph(nodes, edges)

    partition = community_louvain.best_partition(G, weight="weight", random_state=42)

    emails = list(partition.keys())
    labels = [partition[e] for e in emails]
    n_clusters = len(set(labels))

    if use_llm:
        cluster_names = assign_cluster_names_llm(emails, labels, G)
    else:
        cluster_names = None
    if cluster_names is None:
        cluster_names = assign_cluster_names_rule(G, emails, labels)
    write_clusters(driver, emails, labels, cluster_names, silent=silent)

    if not silent:
        print(f"\nLouvain detected {n_clusters} communities:\n")
        for cluster_id in range(n_clusters):
            name = cluster_names[cluster_id] if cluster_id < len(cluster_names) else f"Community {cluster_id}"
            members = [emails[i] for i, l in enumerate(labels) if l == cluster_id]
            member_names = [str(G.nodes[e].get("name") or e) for e in members]
            print(f"  {name}: {', '.join(member_names)}")

    return partition


_cluster_lock = threading.Lock()


def ensure_clustered(driver, force=False):
    """
    If any Person has no cluster (or force=True), run Louvain and write cluster/cluster_name.
    Safe to call on every request; only runs when needed. Thread-safe.
    """
    with _cluster_lock:
        with driver.session() as session:
            r = session.run(
                "MATCH (p:Person) WITH count(p) AS total, count(p.cluster) AS with_cluster RETURN total, with_cluster"
            ).single()
            if not r or r["total"] == 0:
                return
            total, with_cluster = r["total"], r["with_cluster"]
        if not force and with_cluster >= total:
            return
        run_louvain(driver, use_llm=True, silent=True)


def assign_cluster_names_rule(G, emails, labels):
    """
    Assign a category name to each cluster based on graph structure (no API).
    Uses size + role: e.g. "Primary community", "Bridge group", "Periphery".
    """
    n_clusters = len(set(labels))
    degree = dict(G.degree(weight="weight"))
    betweenness = nx.betweenness_centrality(G)

    # Per-cluster: members, size, avg degree, avg betweenness
    clusters = {i: [] for i in range(n_clusters)}
    for i, email in enumerate(emails):
        c = labels[i]
        clusters[c].append((email, degree.get(email, 0), betweenness.get(email, 0)))

    # Sort by size (desc) to assign Primary, Secondary, ...
    size_order = sorted(range(n_clusters), key=lambda c: len(clusters[c]), reverse=True)
    role_names = []
    for c in size_order:
        members = clusters[c]
        n = len(members)
        avg_deg = sum(m[1] for m in members) / n if n else 0
        avg_bet = sum(m[2] for m in members) / n if n else 0
        # Simple role: by size rank
        rank = size_order.index(c)
        if rank == 0:
            name = "Primary community"
        elif rank == 1:
            name = "Secondary community"
        elif rank == 2:
            name = "Tertiary community"
        else:
            name = f"Community {rank + 1}"
        role_names.append((c, name))

    # Order by cluster id for indexing
    names_by_id = {c: name for c, name in role_names}
    return [names_by_id[i] for i in range(n_clusters)]


def _cluster_relationship_summary(G, cluster_emails, email_to_name, max_edges=25):
    """
    Build a short summary of relationships within a cluster: who communicates with whom
    and how strongly (email count). Used so the LLM can name based on relationship type.
    """
    sub = G.subgraph(cluster_emails)
    def name(e):
        v = email_to_name.get(e, e)
        return v if v is not None else e
    edges = []
    for u, v, d in sub.edges(data=True):
        w = d.get("weight", 1)
        edges.append((name(u), name(v), w))
    edges.sort(key=lambda x: -x[2])  # strongest first
    if len(edges) > max_edges:
        edges = edges[:max_edges]
    if not edges:
        return "Members have no recorded communication with each other within this group."
    parts = [f"{a or '?'}–{b or '?'} ({w} emails)" for a, b, w in edges]
    return "Relationships (name–name, email count): " + "; ".join(parts)


def assign_cluster_names_llm(emails, labels, G):
    """
    Use OpenRouter to suggest a short category name per cluster based on member names
    and their communication relationships. Requires OPENROUTER_API_KEY in config (.env).
    Returns list of names indexed by cluster id.
    """
    api_key = (OPENROUTER_API_KEY or os.environ.get("OPENROUTER_API_KEY") or "").strip()
    if not api_key:
        print("[clustering] OPENROUTER_API_KEY not set; using rule-based cluster names.")
        return None

    n_clusters = len(set(labels))
    # Use name or email; never None (Neo4j can return name: null)
    email_to_name = {e: (G.nodes[e].get("name") or e) for e in G.nodes()}
    clusters = {i: [] for i in range(n_clusters)}
    for i, email in enumerate(emails):
        clusters[labels[i]].append(email)

    names = []
    try:
        import urllib.request
        import json
        print(f"[clustering] Calling LLM for {n_clusters} cluster names...")
        for c in range(n_clusters):
            cluster_emails = clusters[c]
            member_list = ", ".join(str(email_to_name[e] or e) for e in cluster_emails[:25])
            if len(cluster_emails) > 25:
                member_list += f" (+{len(cluster_emails) - 25} more)"
            relationship_summary = _cluster_relationship_summary(
                G, cluster_emails, email_to_name
            )
            prompt = (
                "Suggest a short category name (2-4 words) for this group based on who they are and how they relate. "
                "The name should reflect the overall relationships (e.g. 'Core leadership', 'Frequent collaborators', "
                "'Cross-team partners', 'Light-touch contacts'). Reply with only the category name, nothing else.\n\n"
                f"Members: {member_list}\n\n{relationship_summary}"
            )
            body = {
                "model": "openai/gpt-4o-mini",
                "messages": [{"role": "user", "content": prompt}],
            }
            req = urllib.request.Request(
                "https://openrouter.ai/api/v1/chat/completions",
                data=json.dumps(body).encode(),
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode())
            err = data.get("error")
            if err:
                err_msg = err.get("message", err) if isinstance(err, dict) else str(err)
                raise RuntimeError(f"OpenRouter API error: {err_msg}")
            text = (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
            name = text.split("\n")[0].strip() if text else f"Cluster {c}"
            names.append(name)
        print(f"[clustering] LLM names assigned: {names}")
        return names
    except Exception as e:
        print(f"[clustering] LLM naming failed: {e}; using rule-based names.")
        return None


def write_clusters(driver, emails, labels, cluster_names=None, silent=False):
    """Write cluster id and optional cluster_name back to Neo4j Person nodes."""
    with driver.session() as session:
        for email, label in zip(emails, labels):
            cid = int(label)
            if cluster_names is not None and cid < len(cluster_names):
                session.run(
                    "MATCH (p:Person {email: $email}) SET p.cluster = $cluster, p.cluster_name = $cluster_name",
                    email=email, cluster=cid, cluster_name=cluster_names[cid],
                )
            else:
                session.run(
                    "MATCH (p:Person {email: $email}) SET p.cluster = $cluster REMOVE p.cluster_name",
                    email=email, cluster=cid,
                )
    if not silent:
        print(f"Wrote cluster (and cluster_name) to {len(emails)} nodes in Neo4j.")


def main():
    if len(sys.argv) < 2:
        print(__doc__.strip())
        sys.exit(1)

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = [a.lower() for a in sys.argv[1:] if a.startswith("--")]
    use_llm = "--llm" in flags

    method = args[0].lower() if args else ""
    n_clusters = int(args[1]) if len(args) > 1 else 4

    driver = get_driver()

    if method == "kmeans":
        run_kmeans(driver, n_clusters=n_clusters, use_llm=use_llm)
    elif method == "louvain":
        run_louvain(driver, use_llm=use_llm)
    else:
        print(f"Unknown method: {method}")
        print("Use 'kmeans' or 'louvain'")
        sys.exit(1)

    driver.close()


if __name__ == "__main__":
    main()
