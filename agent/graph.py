from __future__ import annotations

from neo4j import GraphDatabase
from config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD

import os
import json

_aliases = None

def email_to_name(email: str) -> str:
    global _aliases
    email = email.strip()
    
    # If it's not an email, assume it's already a canonical Name and return as-is
    if "@" not in email:
        return email

    # For emails, normalize to lowercase and check for aliases
    email_lower = email.lower()
    if _aliases is None:
        _aliases = {}
        possible_paths = ["agent/aliases.json", "aliases.json"]
        for p in possible_paths:
            if os.path.exists(p):
                with open(p, "r") as f:
                    _aliases = json.load(f)
                break
    return _aliases.get(email_lower, email_lower)

def normalize_pair(a: str, b: str) -> tuple[str, str]:
    """Return emails in sorted order so undirected edges always match."""
    return (min(a, b), max(a, b))


def get_driver():
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


def ensure_constraints(driver):
    """Create uniqueness constraint on Person.email so merges are idempotent."""
    with driver.session() as session:
        session.run(
            "CREATE CONSTRAINT IF NOT EXISTS "
            "FOR (p:Person) REQUIRE p.email IS UNIQUE"
        )


def upsert_person(tx, email: str):
    name = email_to_name(email)
    tx.run("MERGE (p:Person {email: $name})", name=name)


def upsert_persons(tx, emails: list[str]) -> None:
    """Upsert all given emails as canonical Person nodes in one transaction."""
    for email in emails:
        name = email_to_name(email)
        tx.run("MERGE (p:Person {email: $name})", name=name)


def append_comment(tx, email_a: str, email_b: str, comment: str):
    """Normalize pair order, MERGE edge, append comment to list."""
    name_a = email_to_name(email_a)
    name_b = email_to_name(email_b)
    lo, hi = normalize_pair(name_a, name_b)
    tx.run(
        "MATCH (a:Person {email: $lo}), (b:Person {email: $hi}) "
        "MERGE (a)-[r:COMMUNICATES_WITH]-(b) "
        "ON CREATE SET r.comments = [$comment], r.email_count = 0 "
        "ON MATCH SET r.comments = r.comments + $comment",
        lo=lo, hi=hi, comment=comment,
    )

def append_comment_cross(
    tx,
    a_emails: list[str],
    b_emails: list[str],
    comment: str,
) -> None:
    """
    Append the same comment to every (a, b) edge for a in a_emails, b in b_emails.
    Creates O(len(a_emails) * len(b_emails)) edges (skips self, dedupes by pair).
    Use for e.g. one group emailed another, or one sender to many recipients.
    """
    seen: set[tuple[str, str]] = set()
    for a in a_emails:
        for b in b_emails:
            if a == b:
                continue
            pair = normalize_pair(a, b)
            if pair in seen:
                continue
            seen.add(pair)
            append_comment(tx, a, b, comment)


def append_comment_batch(tx, from_email: str, to_emails: list[str], comment: str):
    """Append the same comment to multiple (from_email, to_email) edges in one transaction."""
    append_comment_cross(tx, [from_email], to_emails, comment)


def append_comment_recipient_pairs(
    tx, recipient_emails: list[str], comment: str
) -> None:
    """
    Link every pair of recipients with the same comment (e.g. "copied together on same email").
    """
    append_comment_cross(tx, recipient_emails, recipient_emails, comment)


def increment_email_count(tx, email_a: str, email_b: str):
    """Bump email_count by 1 for a pair (called once per email per pair)."""
    name_a = email_to_name(email_a)
    name_b = email_to_name(email_b)
    lo, hi = normalize_pair(name_a, name_b)
    tx.run(
        "MATCH (a:Person {email: $lo})-[r:COMMUNICATES_WITH]-(b:Person {email: $hi}) "
        "SET r.email_count = coalesce(r.email_count, 0) + 1",
        lo=lo, hi=hi,
    )


def increment_email_count_batch(tx, pairs: list[tuple[str, str]]) -> None:
    """Bump email_count by 1 for each pair in one transaction using UNWIND."""
    normalized = []
    for a, b in pairs:
        name_a = email_to_name(a)
        name_b = email_to_name(b)
        lo, hi = normalize_pair(name_a, name_b)
        normalized.append({"lo": lo, "hi": hi})
    
    tx.run(
        "UNWIND $batch AS item "
        "MATCH (a:Person {email: item.lo})-[r:COMMUNICATES_WITH]-(b:Person {email: item.hi}) "
        "SET r.email_count = coalesce(r.email_count, 0) + 1",
        batch=normalized
    )


def get_comments(tx, email_a: str, email_b: str) -> list[str]:
    name_a = email_to_name(email_a)
    name_b = email_to_name(email_b)
    lo, hi = normalize_pair(name_a, name_b)
    result = tx.run(
        "MATCH (a:Person {email: $lo})-[r:COMMUNICATES_WITH]-(b:Person {email: $hi}) "
        "RETURN r.comments AS comments",
        lo=lo, hi=hi,
    )
    record = result.single()
    return record["comments"] if record else []


def set_summary(tx, email_a: str, email_b: str, summary: str):
    name_a = email_to_name(email_a)
    name_b = email_to_name(email_b)
    lo, hi = normalize_pair(name_a, name_b)
    tx.run(
        "MATCH (a:Person {email: $lo})-[r:COMMUNICATES_WITH]-(b:Person {email: $hi}) "
        "SET r.summary = $summary",
        lo=lo, hi=hi, summary=summary,
    )


def set_summary_batch(tx, updates: list[tuple[str, str, str]]) -> None:
    """Set summary for multiple edges using UNWIND."""
    normalized = []
    for a, b, summary in updates:
        name_a = email_to_name(a)
        name_b = email_to_name(b)
        lo, hi = normalize_pair(name_a, name_b)
        normalized.append({"lo": lo, "hi": hi, "summary": summary})
    
    tx.run(
        "UNWIND $batch AS item "
        "MATCH (a:Person {email: item.lo})-[r:COMMUNICATES_WITH]-(b:Person {email: item.hi}) "
        "SET r.summary = item.summary",
        batch=normalized
    )


def get_all_edges(tx) -> list[dict]:
    """Return every edge that has at least one comment."""
    result = tx.run(
        "MATCH (a:Person)-[r:COMMUNICATES_WITH]-(b:Person) "
        "WHERE a.email < b.email AND size(r.comments) > 0 "
        "RETURN a.email AS email_a, b.email AS email_b, "
        "r.comments AS comments, r.summary AS summary"
    )
    return [record.data() for record in result]