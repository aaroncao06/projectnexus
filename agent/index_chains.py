"""Index email chain data from CSV into Pinecone.

Optimized for throughput: large embedding batches on GPU, concurrent Pinecone upserts.

Usage:
    python index_chains.py /path/to/chain_emil_final.csv
"""

import hashlib
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from embeddings import embed_texts
from pinecone_client import get_index

ROWS_PER_BATCH = 500
MAX_CHAIN_CHARS = 1000
PINECONE_UPSERT_BATCH = 100
UPSERT_WORKERS = 4


def chunk_chain(text: str) -> list[str]:
    """Split a chain_text into chunks if it exceeds MAX_CHAIN_CHARS."""
    if len(text) <= MAX_CHAIN_CHARS:
        return [text]
    chunks = []
    stride = MAX_CHAIN_CHARS // 2
    for start in range(0, len(text), stride):
        segment = text[start : start + MAX_CHAIN_CHARS]
        chunks.append(segment)
        if start + MAX_CHAIN_CHARS >= len(text):
            break
    return chunks


def upsert_batch(index, vectors, namespace):
    """Upsert a single batch to Pinecone."""
    index.upsert(vectors=vectors, namespace=namespace)


def parallel_upsert(vectors: list[dict], namespace: str):
    """Upsert vectors to Pinecone using concurrent threads."""
    index = get_index()
    batches = [
        vectors[i : i + PINECONE_UPSERT_BATCH]
        for i in range(0, len(vectors), PINECONE_UPSERT_BATCH)
    ]
    with ThreadPoolExecutor(max_workers=UPSERT_WORKERS) as executor:
        futures = [
            executor.submit(upsert_batch, index, batch, namespace)
            for batch in batches
        ]
        for f in futures:
            f.result()


def flush_batch(chunks: list[dict]):
    """Embed and upsert a batch of chunks."""
    texts = [c["text"] for c in chunks]
    embeddings = embed_texts(texts)

    vectors = []
    for chunk, emb in zip(chunks, embeddings):
        meta = {**chunk["metadata"], "text": chunk["text"][:1000]}
        vectors.append({"id": chunk["id"], "values": emb, "metadata": meta})

    parallel_upsert(vectors, namespace="email_chains")


def index_chains(csv_path: str):
    print(f"Reading {csv_path}...")
    df = pd.read_csv(csv_path)
    total = len(df)
    print(f"  {total} email threads to index")

    batch = []
    indexed_total = 0
    start_time = time.time()

    for row_idx, (_, row) in enumerate(df.iterrows()):
        chain_text = str(row.get("chain_text", ""))
        if not chain_text.strip():
            continue

        thread_id = str(row.get("thread_id", row_idx))
        subject = str(row.get("subject", ""))
        prediction = int(row.get("prediction", 0))
        confidence = float(row.get("confidence", 0))
        n_messages = int(row.get("n_messages", 0))

        chunks = chunk_chain(chain_text)
        for i, chunk_text in enumerate(chunks):
            chunk_id = hashlib.md5(f"{thread_id}_{i}".encode()).hexdigest()
            batch.append(
                {
                    "id": chunk_id,
                    "text": chunk_text,
                    "metadata": {
                        "type": "email_chain",
                        "thread_id": thread_id,
                        "subject": subject,
                        "chunk_index": i,
                        "prediction": prediction,
                        "confidence": confidence,
                        "n_messages": n_messages,
                    },
                }
            )

        if (row_idx + 1) % ROWS_PER_BATCH == 0 and batch:
            flush_batch(batch)
            indexed_total += len(batch)
            elapsed = time.time() - start_time
            rate = (row_idx + 1) / elapsed
            eta_min = (total - row_idx - 1) / rate / 60
            print(
                f"  {row_idx + 1}/{total} threads "
                f"({indexed_total} chunks) "
                f"[{rate:.0f} threads/s, ETA {eta_min:.0f}m]"
            )
            batch = []

    if batch:
        flush_batch(batch)
        indexed_total += len(batch)

    elapsed = time.time() - start_time
    print(f"\n=== Done — {indexed_total} chunks indexed in {elapsed / 60:.1f} minutes ===")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python index_chains.py /path/to/chain_emil_final.csv")
        sys.exit(1)
    index_chains(sys.argv[1])
