# Diagnostic script for RAG/Pinecone
# Run from the backend folder (or with repo root on PYTHONPATH):
# python backend/scripts/check_rag.py

import os
import sys
from pathlib import Path

# Ensure repo root is on path so imports work when running from anywhere
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Ensure project subpackages that rely on top-level `config` import are on path
BACKEND_DIR = REPO_ROOT / "backend"
AGENT_DIR = REPO_ROOT / "agent"
for p in (str(BACKEND_DIR), str(AGENT_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)
        print("Added to sys.path:", p)

# Load .env if present
from dotenv import load_dotenv
load_dotenv(REPO_ROOT / ".env")

print("Loaded .env from", REPO_ROOT / ".env")

# Show key env vars we'll use
print("OPENROUTER_API_KEY set:", bool(os.getenv("OPENROUTER_API_KEY")))
print("OPENAI_API_KEY set:", bool(os.getenv("OPENAI_API_KEY")))
print("PINECONE_API_KEY set:", bool(os.getenv("PINECONE_API_KEY")))

# Import project helpers. Try normal imports first; if the repo subfolders
# aren't packages (no __init__.py), fall back to loading by file path.
import importlib
import importlib.util

def _load_module_from_path(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    if spec is None or spec.loader is None:
        raise ImportError(f"Can't load module {module_name} from {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

try:
    from agent.pinecone_client import get_index  # type: ignore
    from backend.vectorstore import search, get_retriever  # type: ignore
except Exception as e:
    print("Import error with package-style imports, falling back to file imports:", e)
    AGENT_DIR = REPO_ROOT / "agent"
    BACKEND_DIR = REPO_ROOT / "backend"
    pc_path = AGENT_DIR / "pinecone_client.py"
    vs_path = BACKEND_DIR / "vectorstore.py"
    try:
        # agent.pinecone_client expects to import `config` (the agent config).
        # Load agent/config.py into sys.modules as 'config' temporarily.
        agent_cfg_path = AGENT_DIR / "config.py"
        agent_cfg_mod = _load_module_from_path("agent_config", agent_cfg_path)
        sys.modules["config"] = agent_cfg_mod
        pc_mod = _load_module_from_path("agent_pinecone_client", pc_path)
        get_index = pc_mod.get_index
    except Exception as e2:
        print("Failed to load agent.pinecone_client:", e2)
        raise
    try:
        # Now load backend config as 'config' so backend.vectorstore imports resolve to backend/config.py
        backend_cfg_path = BACKEND_DIR / "config.py"
        backend_cfg_mod = _load_module_from_path("backend_config", backend_cfg_path)
        sys.modules["config"] = backend_cfg_mod
        vs_mod = _load_module_from_path("backend_vectorstore", vs_path)
        search = vs_mod.search
        get_retriever = vs_mod.get_retriever
    except Exception as e3:
        print("Failed to load backend.vectorstore:", e3)
        raise

print("Checking Pinecone index handle and stats...")
try:
    idx = get_index()
    print("Got index object:", type(idx))
    try:
        stats = idx.describe_index_stats()
        print("Index stats:", stats)
    except Exception as e:
        print("Could not get index stats (method may vary by client):", e)
except Exception as e:
    print("Failed to get or create index:", e)

# Try searching the namespace used by the project
namespaces = ["epstein_emails", "epstein_emails_chunks", "epstein"]
for ns in namespaces:
    print(f"\nRunning vectorstore.search for namespace '{ns}'...")
    try:
        results = search("jeffrey epstein ghislaine maxwell", namespaces=[ns], top_k=5)
        print(f"Returned {len(results)} results for namespace '{ns}'")
        if results:
            for i, r in enumerate(results[:3], 1):
                print(f"[{i}] namespace={r.get('namespace')} score={r.get('score')} type={r.get('type')} preview={r.get('text','')[:200]!r}")
    except Exception as e:
        print("Search failed:", e)

# Try calling retriever directly
print("\nTesting retriever.invoke() for default namespaces")
try:
    retr = get_retriever()
    docs = retr.invoke("jeffrey epstein ghislaine maxwell")
    print("Retriever.invoke returned", len(docs), "documents")
    for d in docs[:3]:
        print("- doc metadata:", d.metadata)
except Exception as e:
    print("Retriever invoke failed:", e)

print("\nDiagnostic complete.")
