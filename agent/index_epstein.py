"""Index Epstein email CSV into Pinecone.

Usage:
    python index_epstein.py /path/to/epstein_email.csv
"""

import hashlib
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from embeddings import embed_texts
from pinecone_client import get_index

ROWS_PER_BATCH = 200
MAX_CHUNK_CHARS = 1000
PINECONE_UPSERT_BATCH = 100
UPSERT_WORKERS = 4


def chunk_text(text: str) -> list[str]:
    if len(text) <= MAX_CHUNK_CHARS:
        return [text]
    chunks = []
    stride = MAX_CHUNK_CHARS // 2
    for start in range(0, len(text), stride):
        segment = text[start : start + MAX_CHUNK_CHARS]
        chunks.append(segment)
        if start + MAX_CHUNK_CHARS >= len(text):
            break
    return chunks


def parallel_upsert(vectors: list[dict], namespace: str):
    index = get_index()
    batches = [
        vectors[i : i + PINECONE_UPSERT_BATCH]
        for i in range(0, len(vectors), PINECONE_UPSERT_BATCH)
    ]
    with ThreadPoolExecutor(max_workers=UPSERT_WORKERS) as executor:
        futures = [
            executor.submit(lambda b: index.upsert(vectors=b, namespace=namespace), batch)
            for batch in batches
        ]
        for f in futures:
            f.result()


def flush_batch(chunks: list[dict]):
    texts = [c["text"] for c in chunks]
    embeddings = embed_texts(texts)

    vectors = []
    for chunk, emb in zip(chunks, embeddings):
        meta = {**chunk["metadata"], "text": chunk["text"][:1000]}
        vectors.append({"id": chunk["id"], "values": emb, "metadata": meta})

    parallel_upsert(vectors, namespace="epstein_emails")


def index_epstein(csv_path: str):
    print(f"Reading {csv_path}...")
    df = pd.read_csv(csv_path)
    total = len(df)
    print(f"  {total} emails to index")

    batch = []
    indexed_total = 0
    start_time = time.time()

    for row_idx, (_, row) in enumerate(df.iterrows()):
        email_text = str(row.get("email_text_clean", ""))
        if not email_text.strip():
            continue

        source_file = str(row.get("source_file", ""))
        subject = str(row.get("subject", ""))
        date = str(row.get("date", ""))
        participants = str(row.get("participants", ""))
        notable_figures = str(row.get("notable_figures", ""))
        summary = str(row.get("summary", ""))
        primary_topic = str(row.get("primary_topic", ""))
        topics = str(row.get("topics", ""))
        tone = str(row.get("tone", ""))
        organizations = str(row.get("organizations", ""))
        locations = str(row.get("locations", ""))

        # Prepend summary as context for better retrieval
        enriched_prefix = (
            f"Subject: {subject} | Date: {date} | "
            f"Participants: {participants} | "
            f"Summary: {summary}\n\n"
        )

        chunks = chunk_text(email_text)
        for i, chunk_text_str in enumerate(chunks):
            full_text = enriched_prefix + chunk_text_str if i == 0 else chunk_text_str
            chunk_id = hashlib.md5(f"epstein_{source_file}_{i}".encode()).hexdigest()
            batch.append(
                {
                    "id": chunk_id,
                    "text": full_text,
                    "metadata": {
                        "type": "epstein_email",
                        "source_file": source_file,
                        "subject": subject,
                        "date": date,
                        "participants": participants[:500],
                        "notable_figures": notable_figures[:500],
                        "primary_topic": primary_topic,
                        "topics": topics[:200],
                        "tone": tone,
                        "organizations": organizations[:500],
                        "locations": locations[:500],
                        "summary": summary[:500],
                        "chunk_index": i,
                    },
                }
            )

        if (row_idx + 1) % ROWS_PER_BATCH == 0 and batch:
            flush_batch(batch)
            indexed_total += len(batch)
            elapsed = time.time() - start_time
            rate = (row_idx + 1) / elapsed
            eta_s = (total - row_idx - 1) / rate
            print(
                f"  {row_idx + 1}/{total} emails "
                f"({indexed_total} chunks) "
                f"[{rate:.0f} emails/s, ETA {eta_s:.0f}s]"
            )
            batch = []

    if batch:
        flush_batch(batch)
        indexed_total += len(batch)

    elapsed = time.time() - start_time
    print(f"\n=== Done — {indexed_total} chunks indexed in {elapsed:.1f}s ===")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python index_epstein.py /path/to/epstein_email.csv")
        sys.exit(1)
    index_epstein(sys.argv[1])
