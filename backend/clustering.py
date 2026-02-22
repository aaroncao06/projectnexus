"""
Graph clustering using K-Means and Louvain community detection.

Pulls graph data from Neo4j, computes clusters, and writes
a `cluster` property back onto each Person node.

Usage:
    python clustering.py kmeans   # K-Means on feature vectors (degree, email volume, etc.)
    python clustering.py louvain  # Louvain community detection (graph structure)
"""

import sys
import numpy as np
from sklearn.cluster import KMeans
from sklearn.preprocessing import StandardScaler
import networkx as nx
from community import community_louvain  # python-louvain

from neo4j import GraphDatabase
from config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD


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


def run_kmeans(driver, n_clusters=4):
    """Run K-Means clustering and write results back to Neo4j."""
    print(f"Running K-Means clustering (k={n_clusters})...")

    nodes, edges = fetch_graph_data(driver)
    G = build_networkx_graph(nodes, edges)
    emails, X = build_feature_matrix(G)

    # Standardize features
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    # Clamp k to number of nodes
    k = min(n_clusters, len(emails))
    kmeans = KMeans(n_clusters=k, random_state=42, n_init=10)
    labels = kmeans.fit_predict(X_scaled)

    # Write cluster labels back to Neo4j
    write_clusters(driver, emails, labels)

    # Print results
    print(f"\nK-Means clustering complete ({k} clusters):\n")
    for cluster_id in range(k):
        members = [emails[i] for i, l in enumerate(labels) if l == cluster_id]
        names = [G.nodes[e].get("name", e) for e in members]
        print(f"  Cluster {cluster_id}: {', '.join(names)}")

    return dict(zip(emails, [int(l) for l in labels]))


def run_louvain(driver):
    """Run Louvain community detection and write results back to Neo4j."""
    print("Running Louvain community detection...")

    nodes, edges = fetch_graph_data(driver)
    G = build_networkx_graph(nodes, edges)

    # Run Louvain
    partition = community_louvain.best_partition(G, weight="weight", random_state=42)

    emails = list(partition.keys())
    labels = [partition[e] for e in emails]

    # Write cluster labels back to Neo4j
    write_clusters(driver, emails, labels)

    n_clusters = len(set(labels))
    print(f"\nLouvain detected {n_clusters} communities:\n")
    for cluster_id in range(n_clusters):
        members = [emails[i] for i, l in enumerate(labels) if l == cluster_id]
        names = [G.nodes[e].get("name", e) for e in members]
        print(f"  Community {cluster_id}: {', '.join(names)}")

    return partition


def write_clusters(driver, emails, labels):
    """Write cluster labels back to Neo4j Person nodes."""
    with driver.session() as session:
        for email, label in zip(emails, labels):
            session.run(
                "MATCH (p:Person {email: $email}) SET p.cluster = $cluster",
                email=email, cluster=int(label),
            )
    print(f"Wrote cluster labels to {len(emails)} nodes in Neo4j.")


def main():
    if len(sys.argv) < 2:
        print(__doc__.strip())
        sys.exit(1)

    method = sys.argv[1].lower()
    n_clusters = int(sys.argv[2]) if len(sys.argv) > 2 else 4

    driver = get_driver()

    if method == "kmeans":
        run_kmeans(driver, n_clusters=n_clusters)
    elif method == "louvain":
        run_louvain(driver)
    else:
        print(f"Unknown method: {method}")
        print("Use 'kmeans' or 'louvain'")
        sys.exit(1)

    driver.close()


if __name__ == "__main__":
    main()
