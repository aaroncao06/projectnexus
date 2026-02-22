"""Index filtered Enron email CSV into Pinecone.

Usage:
    python index_enron_filtered.py /path/to/enron_filter_final_df.csv
"""

import hashlib
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from embeddings import embed_texts
from pinecone_client import get_index

ROWS_PER_BATCH = 500
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


def _upsert_with_retry(index, batch, namespace, max_retries=5):
    for attempt in range(max_retries):
        try:
            index.upsert(vectors=batch, namespace=namespace)
            return
        except Exception as e:
            if attempt < max_retries - 1:
                wait = 2 ** attempt
                print(f"    Upsert failed ({e}), retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise


def parallel_upsert(vectors: list[dict], namespace: str):
    index = get_index()
    batches = [
        vectors[i : i + PINECONE_UPSERT_BATCH]
        for i in range(0, len(vectors), PINECONE_UPSERT_BATCH)
    ]
    with ThreadPoolExecutor(max_workers=UPSERT_WORKERS) as executor:
        futures = [
            executor.submit(_upsert_with_retry, index, batch, namespace)
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

    parallel_upsert(vectors, namespace="enron_filtered")


def index_enron(csv_path: str):
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
        emails = str(row.get("email", ""))

        chunks = chunk_text(chain_text)
        for i, chunk_text_str in enumerate(chunks):
            chunk_id = hashlib.md5(f"enron_{thread_id}_{i}".encode()).hexdigest()
            batch.append(
                {
                    "id": chunk_id,
                    "text": chunk_text_str,
                    "metadata": {
                        "type": "enron_email",
                        "thread_id": thread_id,
                        "subject": subject,
                        "chunk_index": i,
                        "prediction": prediction,
                        "confidence": confidence,
                        "n_messages": n_messages,
                        "emails": emails[:500],
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
        print("Usage: python index_enron_filtered.py /path/to/enron_filter_final_df.csv")
        sys.exit(1)
    index_enron(sys.argv[1])
