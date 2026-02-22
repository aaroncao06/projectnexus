"""Index relationship summaries from Neo4j into Pinecone.

Usage:
    python index_relationships.py
"""

import hashlib

from graph import get_driver
from embeddings import embed_texts
from pinecone_client import upsert_vectors


def fetch_relationship_summaries(driver) -> list[dict]:
    """Query Neo4j for all relationships and build text summaries."""
    with driver.session() as session:
        result = session.run(
            "MATCH (a:Person)-[r:COMMUNICATES_WITH]->(b:Person) "
            "RETURN a.name AS from_name, a.email AS from_email, "
            "b.name AS to_name, b.email AS to_email, "
            "properties(r) AS props"
        )
        summaries = []
        for record in result:
            data = record.data()
            count = data["props"].get("count", 0)
            text = (
                f"{data['from_name']} ({data['from_email']}) communicated with "
                f"{data['to_name']} ({data['to_email']}) {count} times."
            )
            summaries.append(
                {
                    "text": text,
                    "from_email": data["from_email"],
                    "to_email": data["to_email"],
                    "from_name": data["from_name"],
                    "to_name": data["to_name"],
                    "count": count,
                }
            )
    return summaries


def index_all_relationships():
    driver = get_driver()
    summaries = fetch_relationship_summaries(driver)
    driver.close()

    if not summaries:
        print("No relationships found in Neo4j.")
        return

    texts = [s["text"] for s in summaries]
    embeddings = embed_texts(texts)

    vectors = []
    for s, emb in zip(summaries, embeddings):
        vid = hashlib.md5(f"{s['from_email']}_{s['to_email']}".encode()).hexdigest()
        vectors.append(
            {
                "id": vid,
                "values": emb,
                "metadata": {
                    "type": "relationship",
                    "text": s["text"],
                    "from_email": s["from_email"],
                    "to_email": s["to_email"],
                    "from_name": s["from_name"],
                    "to_name": s["to_name"],
                    "count": s["count"],
                },
            }
        )

    upsert_vectors(vectors, namespace="relationships")
    print(f"Indexed {len(vectors)} relationship summaries.")


if __name__ == "__main__":
    index_all_relationships()
