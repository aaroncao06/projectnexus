import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root (parent of backend/)
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "nexus_pass")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
