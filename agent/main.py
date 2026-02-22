"""
AI Agent CLI.

Usage:
    python main.py ingest          Run agent on a sample email chain.
    python main.py ingest-fake     Run agent on all fake test chains.
    python main.py summarize       Generate summaries for all annotated edges.
"""

import sys

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
    elif command == "summarize":
        summarize_edges()
    else:
        print(f"Unknown command: {command}")
        print(__doc__.strip())
        sys.exit(1)


if __name__ == "__main__":
    main()
