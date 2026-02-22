"""Index email content from parquet files into Pinecone.

Processes emails in small batches (default 500) to avoid rate limits.

Usage:
    python index_emails.py                  # index all parquet files
    python index_emails.py emails_part_1    # index a specific file (without .parquet)
"""

import hashlib
import os
import sys

import pandas as pd

from config import EMAIL_CHUNKS_DIR
from embeddings import embed_texts, chunk_email
from pinecone_client import upsert_vectors

EMAILS_PER_BATCH = 500


def index_parquet(path: str):
    """Read a single parquet file, chunk emails, embed, and upsert to Pinecone in batches."""
    filename = os.path.basename(path)
    print(f"\n=== Processing {filename} ===")
    df = pd.read_parquet(path)
    total_rows = len(df)
    print(f"  {total_rows} emails in file")

    batch_chunks = []
    indexed_total = 0

    for row_idx, (_, row) in enumerate(df.iterrows()):
        raw = row.get("message", "")
        if not raw or not isinstance(raw, str):
            continue
        file_id = row.get("file", str(row_idx))
        chunks = chunk_email(raw)
        for i, chunk in enumerate(chunks):
            chunk_id = hashlib.md5(f"{file_id}_{i}".encode()).hexdigest()
            batch_chunks.append(
                {
                    "id": chunk_id,
                    "text": chunk["text"],
                    "metadata": {
                        "type": "email",
                        "source_file": str(file_id),
                        "chunk_index": i,
                        "from": chunk.get("from", ""),
                        "to": chunk.get("to", ""),
                        "subject": chunk.get("subject", ""),
                        "date": chunk.get("date", ""),
                    },
                }
            )

        # Flush batch when we've accumulated enough emails
        if (row_idx + 1) % EMAILS_PER_BATCH == 0 and batch_chunks:
            _flush_batch(batch_chunks)
            indexed_total += len(batch_chunks)
            print(f"  [{filename}] {row_idx + 1}/{total_rows} emails processed ({indexed_total} chunks indexed)")
            batch_chunks = []

    # Flush remaining
    if batch_chunks:
        _flush_batch(batch_chunks)
        indexed_total += len(batch_chunks)

    print(f"  [{filename}] Done — {indexed_total} total chunks indexed")


def _flush_batch(chunks: list[dict]):
    """Embed and upsert a batch of chunks."""
    texts = [c["text"] for c in chunks]
    embeddings = embed_texts(texts)

    vectors = []
    for chunk, emb in zip(chunks, embeddings):
        meta = {**chunk["metadata"], "text": chunk["text"][:1000]}
        vectors.append({"id": chunk["id"], "values": emb, "metadata": meta})

    upsert_vectors(vectors, namespace="emails")


def index_all_emails():
    """Index all parquet files found in EMAIL_CHUNKS_DIR, one by one."""
    parquet_dir = EMAIL_CHUNKS_DIR
    files = sorted(f for f in os.listdir(parquet_dir) if f.endswith(".parquet"))
    if not files:
        print(f"No parquet files found in {parquet_dir}")
        return
    print(f"Found {len(files)} parquet files to index")
    for i, f in enumerate(files, 1):
        print(f"\n--- File {i}/{len(files)} ---")
        index_parquet(os.path.join(parquet_dir, f))
    print("\n=== All files indexed successfully ===")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        name = sys.argv[1]
        if not name.endswith(".parquet"):
            name += ".parquet"
        index_parquet(os.path.join(EMAIL_CHUNKS_DIR, name))
    else:
        index_all_emails()
