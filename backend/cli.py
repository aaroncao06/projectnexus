"""CLI tool for querying the Enron email graph.

Usage:
    python cli.py "who communicated most with ken.lay?"
    python cli.py --insights
    python cli.py                  # interactive mode
"""

import sys
from rag import query, generate_graph_insights


def print_result(result: dict):
    print(f"\n{result['answer']}")
    sources = result.get("sources", [])
    if sources:
        print("\n--- Sources ---")
        for s in sources:
            preview = s.get("text_preview", "")[:100]
            print(f"  [{s.get('namespace')}] score={s.get('score', 0):.3f}: {preview}")


def main():
    if len(sys.argv) > 1:
        arg = " ".join(sys.argv[1:])
        if arg.strip() == "--insights":
            result = generate_graph_insights()
            print(f"\n{result['answer']}")
        else:
            result = query(arg)
            print_result(result)
    else:
        print("ProjectNexus Query CLI. Type 'quit' to exit, 'insights' for graph overview.")
        while True:
            try:
                q = input("\n> ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not q:
                continue
            if q.lower() in ("quit", "exit"):
                break
            if q.lower() == "insights":
                result = generate_graph_insights()
                print(f"\n{result['answer']}")
            else:
                result = query(q)
                print_result(result)


if __name__ == "__main__":
    main()
