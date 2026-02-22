"""
Graph insights: anomaly detection, bridge edges, and centrality analysis.

Runs Isolation Forest on node features, detects bridge edges between clusters,
and identifies high-centrality nodes. Results are cached in memory.
"""

import threading
import networkx as nx
import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.preprocessing import StandardScaler

from clustering import fetch_graph_data, build_networkx_graph, build_feature_matrix, get_driver

_cache_lock = threading.Lock()
_cached_insights: list[dict] | None = None


def invalidate_cache():
    """Call after recluster or data changes to force recomputation."""
    global _cached_insights
    with _cache_lock:
        _cached_insights = None


def compute_insights(driver) -> list[dict]:
    """Compute all insights and return sorted by severity (highest first)."""
    global _cached_insights
    with _cache_lock:
        if _cached_insights is not None:
            return _cached_insights

    nodes, edges = fetch_graph_data(driver)
    if not nodes:
        return []

    G = build_networkx_graph(nodes, edges)
    emails, X = build_feature_matrix(G)

    insights: list[dict] = []

    # --- 1. Node anomaly detection (Isolation Forest) ---
    insights.extend(_detect_node_anomalies(G, emails, X))

    # --- 2. Bridge edge detection (cross-cluster edges) ---
    insights.extend(_detect_bridge_edges(G, driver))

    # --- 3. High-centrality nodes ---
    insights.extend(_detect_high_centrality(G))

    # Sort by severity descending
    insights.sort(key=lambda x: x["severity"], reverse=True)

    with _cache_lock:
        _cached_insights = insights

    return insights


def _detect_node_anomalies(G, emails: list[str], X: np.ndarray) -> list[dict]:
    """Use Isolation Forest to find structurally anomalous nodes."""
    if len(emails) < 5:
        return []

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    iso = IsolationForest(
        n_estimators=100,
        contamination=0.15,
        random_state=42,
    )
    iso.fit(X_scaled)
    scores = iso.decision_function(X_scaled)  # lower = more anomalous
    labels = iso.predict(X_scaled)  # -1 = anomaly

    results = []
    degree = dict(G.degree())
    weighted_degree = dict(G.degree(weight="weight"))
    betweenness = nx.betweenness_centrality(G)

    for i, email in enumerate(emails):
        if labels[i] == -1:
            name = G.nodes[email].get("name") or email
            raw_score = -scores[i]  # flip so higher = more anomalous
            severity = round(min(1.0, max(0.0, (raw_score + 0.3) / 0.6)), 2)

            # Build reason string from the features that stand out
            d = degree.get(email, 0)
            wd = weighted_degree.get(email, 0)
            bet = betweenness.get(email, 0)
            reasons = []
            if d >= np.percentile([degree[e] for e in emails], 85):
                reasons.append(f"high connectivity ({d} connections)")
            elif d <= np.percentile([degree[e] for e in emails], 15):
                reasons.append(f"unusually few connections ({d})")
            if wd >= np.percentile([weighted_degree[e] for e in emails], 85):
                reasons.append(f"heavy email volume ({wd} emails)")
            if bet >= np.percentile([betweenness[e] for e in emails], 85):
                reasons.append(f"high betweenness (bridges groups)")

            reason = "; ".join(reasons) if reasons else "unusual feature profile"

            results.append({
                "type": "node_anomaly",
                "title": f"{name}",
                "description": f"Structurally anomalous: {reason}",
                "severity": severity,
                "nodes": [email],
                "edges": [],
            })

    return results


def _detect_bridge_edges(G, driver) -> list[dict]:
    """Find edges that bridge different clusters (cross-cluster connections)."""
    # Fetch cluster info from Neo4j
    from db import read_query
    cluster_data = read_query(
        "MATCH (p:Person) WHERE p.cluster IS NOT NULL "
        "RETURN p.email AS email, p.cluster AS cluster"
    )
    if not cluster_data:
        return []

    email_to_cluster = {r["email"]: r["cluster"] for r in cluster_data}

    # Edge betweenness for ranking importance
    edge_betweenness = nx.edge_betweenness_centrality(G, weight="weight")

    results = []
    for (u, v), eb in sorted(edge_betweenness.items(), key=lambda x: -x[1]):
        cu = email_to_cluster.get(u)
        cv = email_to_cluster.get(v)
        if cu is None or cv is None or cu == cv:
            continue

        name_u = G.nodes[u].get("name") or u
        name_v = G.nodes[v].get("name") or v
        w = G.edges[u, v].get("weight", 1)
        severity = round(min(1.0, eb * 8), 2)  # scale edge betweenness to 0-1

        results.append({
            "type": "bridge_edge",
            "title": f"{name_u} ↔ {name_v}",
            "description": f"Cross-cluster bridge ({w} emails). Connects separate communities.",
            "severity": severity,
            "nodes": [u, v],
            "edges": [{"source": u, "target": v}],
        })

    # Limit to top 15 bridges
    return results[:15]


def _detect_high_centrality(G) -> list[dict]:
    """Identify nodes with exceptionally high PageRank or betweenness."""
    if len(G.nodes()) < 3:
        return []

    pagerank = nx.pagerank(G, weight="weight")
    betweenness = nx.betweenness_centrality(G, weight="weight")

    # Combine into a single influence score
    pr_vals = list(pagerank.values())
    bet_vals = list(betweenness.values())
    pr_mean, pr_std = np.mean(pr_vals), np.std(pr_vals)
    bet_mean, bet_std = np.mean(bet_vals), np.std(bet_vals)

    results = []
    for email in G.nodes():
        pr = pagerank[email]
        bet = betweenness[email]

        # Z-scores
        pr_z = (pr - pr_mean) / pr_std if pr_std > 0 else 0
        bet_z = (bet - bet_mean) / bet_std if bet_std > 0 else 0

        # Flag if either is 1.5+ std devs above mean
        if pr_z < 1.5 and bet_z < 1.5:
            continue

        name = G.nodes[email].get("name") or email
        influence_score = (pr_z + bet_z) / 2
        severity = round(min(1.0, max(0.0, influence_score / 4)), 2)

        parts = []
        if pr_z >= 1.5:
            parts.append(f"top PageRank ({pr:.4f})")
        if bet_z >= 1.5:
            parts.append(f"top betweenness ({bet:.3f})")

        results.append({
            "type": "high_centrality",
            "title": f"{name}",
            "description": f"Key influence node: {', '.join(parts)}",
            "severity": severity,
            "nodes": [email],
            "edges": [],
        })

    return results
