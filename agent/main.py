"""
AI Agent CLI.

Usage:
    python main.py ingest          Run agent on a sample email chain.
    python main.py ingest-fake     Run agent on all fake test chains.
    python main.py ingest-csv [path]  Run agent on each email chain in a CSV (default: epstein_email.csv).
    python main.py summarize [--force] [--workers N]
                                Generate summaries for annotated edges (skips already-summarized by default).
                                --force  re-summarize even if summary exists.
                                --workers N  max concurrent LLM calls (default 8).
"""

import argparse
import ast
import csv
import sys
from pathlib import Path

import pandas as pd
from tqdm import tqdm

from agent import run_agent, run_agent_from_chain_text, summarize_edges
from fake_data import FAKE_CHAINS

SAMPLE_ADDRESSES = [
    "alice@example.com",
    "bob@example.com",
    "carol@example.com",
]

SAMPLE_EMAIL_CHAIN = """\
From: alice@example.com
To: bob@example.com, carol@example.com
Subject: Project kickoff

Hi Bob and Carol,

I'd like to kick off the new analytics dashboard project. Bob, could you \
take the lead on the backend API design? Carol, please handle the frontend \
wireframes and coordinate with Bob on the data contract.

Let's aim to have initial designs by Friday.

Thanks,
Alice

---

From: bob@example.com
To: alice@example.com, carol@example.com
Subject: Re: Project kickoff

Alice,

Sounds good — I'll draft the API spec by Wednesday so Carol has time to \
align the frontend. Carol, let's sync tomorrow to agree on the payload \
format.

Bob

---

From: carol@example.com
To: bob@example.com
Cc: alice@example.com
Subject: Re: Re: Project kickoff

Bob,

Works for me. I have some concerns about the pagination approach from last \
quarter — let's make sure we don't repeat that. I'll prepare a short \
comparison doc before our sync.

Carol
"""


def main():
    if len(sys.argv) < 2:
        print(__doc__.strip())
        sys.exit(1)

    command = sys.argv[1]

    if command == "ingest":
        summary = run_agent(SAMPLE_ADDRESSES, SAMPLE_EMAIL_CHAIN)
        print(f"\nAgent summary:\n{summary}")
    elif command == "ingest-fake":
        for name, chain_text in FAKE_CHAINS:
            print(f"\n--- {name} ---")
            summary = run_agent_from_chain_text(chain_text)
            print(f"Summary: {summary}")
        print("\nDone. Run 'python main.py summarize' to generate edge summaries.")
    elif command == "ingest-csv":
        csv_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).parent / "epstein_email.csv"
        if not csv_path.exists():
            print(f"CSV not found: {csv_path}")
            sys.exit(1)
        # Allow very large email body fields (default limit is 128KB)
        csv.field_size_limit(min(2**31 - 1, sys.maxsize))
        chain_column = "email_text"
        participants_column = "participants"
        people_column = "people_mentioned"
        
        df = pd.read_csv(csv_path)
        total = len(df)
        print(f"Running agent on {total} rows from {csv_path.name} (column: {chain_column})")
        for i, row in tqdm(df.iterrows(), desc="Chains", unit="chain"):
            chain_text = (row[chain_column] or "").strip()
            participants = ast.literal_eval(row[participants_column] or "[]")
            people = ast.literal_eval(row[people_column] or "[]")
            if not chain_text:
                print('empty chain text')
                continue
            try:
                run_agent_from_chain_text(chain_text, list(set(participants) | set(people)))
            except Exception as e:
                tqdm.write(f"Error on row: {e}")
        print("\nDone. Run 'python main.py summarize' to generate edge summaries.")
    elif command == "summarize":
        print('summarizing edges')
        parser = argparse.ArgumentParser(prog="main.py summarize")
        parser.add_argument("--force", action="store_true", help="Re-summarize edges that already have a summary")
        parser.add_argument("--workers", type=int, default=8, metavar="N", help="Max concurrent LLM calls (default 8)")
        args = parser.parse_args(sys.argv[2:])
        summarize_edges(skip_existing=not args.force, max_workers=args.workers)
    else:
        print(f"Unknown command: {command}")
        print(__doc__.strip())
        sys.exit(1)


if __name__ == "__main__":
    main()
