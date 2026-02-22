"""
Agentic LLM loop for extracting relationship comments from email chains.

The LLM reads an email chain and repeatedly calls `add_relationship_comment`
to annotate relationships between people in the Neo4j graph.
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional
import ipdb
import itertools

from openai import OpenAI
from config import OPENROUTER_API_KEY, OPENROUTER_MODEL
from graph import (
    get_driver,
    ensure_constraints,
    upsert_persons,
    append_comment,
    append_comment_batch,
    append_comment_recipient_pairs,
    increment_email_count_batch,
    get_all_edges,
    get_comments,
    set_summary,
    set_summary_batch,
)

client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=OPENROUTER_API_KEY,
)

TOOL_ADD_ONE = {
    "type": "function",
    "function": {
        "name": "add_relationship_comment",
        "description": (
            "Record one observation about the relationship between two people. "
            "Use for a single pair or when each relationship has a different comment."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "from_person": {"type": "string", "description": "The exact Identifier (Name or Email) of one person from the provided list."},
                "to_person": {"type": "string", "description": "The exact Identifier (Name or Email) of the other person from the provided list."},
                "comment": {"type": "string", "description": "Concise observation about this pair."},
            },
            "required": ["from_person", "to_person", "comment"],
        },
    },
}

TOOL_ADD_BATCH = {
    "type": "function",
    "function": {
        "name": "add_relationship_comments_batch",
        "description": (
            "Record the same observation between one central person and multiple other people. "
            "This creates N relationships: one between 'from_person' and each Identifier in 'to_people'. "
            "Example: One person coordinating with many others, or one person mentioned alongside several others."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "from_person": {"type": "string", "description": "The central Identifier from the provided list."},
                "to_people": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of Identifiers for the people who share this relationship with from_person.",
                },
                "comment": {"type": "string", "description": "The observation shared between from_person and each of the to_people."},
            },
            "required": ["from_person", "to_people", "comment"],
        },
    },
}

TOOL_ADD_GROUP = {
    "type": "function",
    "function": {
        "name": "add_relationship_group",
        "description": (
            "Record the same observation for all members of a group. "
            "Creates relationships between every possible pair of people in the list (N*N relationships)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "people": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of exact Identifiers for all people in the group.",
                },
                "comment": {"type": "string", "description": "Concise observation shared by all group members (e.g. 'Co-defendants', 'Same audience on sensitive email')."},
            },
            "required": ["people", "comment"],
        },
    },
}

TOOL_SCHEMAS = [TOOL_ADD_ONE, TOOL_ADD_BATCH, TOOL_ADD_GROUP]

SYSTEM_PROMPT = """\
You are a relationship-extraction agent. You will receive an email chain and \
a list of **Identifiers** for the people involved.

**Crucial Logic for Identifiers:**
- These Identifiers could be **Names** (e.g., "Jeffrey Epstein") or **Email Addresses** (e.g., "jeff@example.com").
- You MUST strictly and exactly use the Identifiers as provided in the list.
- Do NOT change character case, fix typos, or convert an Email into a Name yourself. 
- If a person is mentioned in the text but is NOT in the provided Identifier list, do NOT invent an Identifier for them.

Your goal: help reveal **fraud and suspicious activity** by identifying relationships \
and dynamics that matter for that purpose. Analyse the chain and record only \
**professionally significant** relationships, with special attention to what is **suspicious**.

What is suspicious (prioritise these when present):
- Pressure, urgency, or instructions to act without normal checks (e.g. "wire today", "don't tell anyone").
- Secrecy, off-the-books arrangements, or avoiding written records.
- Unusual money movement, payments, or accounting (e.g. kickbacks, inflated invoices, shell entities).
- Insider or non-public information being shared inappropriately (e.g. tips, advance notice).
- Fake or misleading documents, identities, or credentials.
- Coordination to mislead others (e.g. front-running, cover-ups, false narratives).
- Delegation or reporting that suggests a hidden chain of control or enablers.
- Conflict, distrust, or escalation that hints at wrongdoing (e.g. threats, disputes over proceeds).

Also record other important dynamics (collaboration, delegation, reporting, conflict) that \
reveal roles or power, even when not obviously fraudulent—they can connect to fraud later.

List of tools:
- `add_relationship_comment`: one (from_person, to_person, comment).
- `add_relationship_comments_batch`: (from_person, to_people[], comment). Use when one person \
  has the exact same relationship dynamic with many others simultaneously.
- `add_relationship_group`: (people[], comment). Use when everyone in the list has the exact \
  same relationship to everyone else (clique). This creates an observation between every pair in the group.

Guidelines:
- **Strictly use the Identifiers provided in the list**. Do not change case or format.
- Only use people (names or emails) from the provided list.
- **Only record observations that are investigatively useful.** This tool exists to \
uncover fraud and crime. Every comment should reveal something suspicious, expose a \
power dynamic, or document a pattern that could connect to wrongdoing. Do NOT record \
mundane professional interactions, routine coordination, or anything an investigator \
would not care about.
- **CRITICAL: Limit your output to under 3 tool calls per chain.** Focus on the highest-priority insights.
- **Comments must be self-contained**: each comment should be understandable on its own, \
without access to the original email. Include enough context (what happened, what was \
requested, why it matters) so someone reading only the comment can grasp the insight. \
Keep it to 1–2 sentences—concise, but never so vague that the reader can't tell what occurred.
- Do NOT add relationships for: routine FYI, out-of-office, single logistical reply, or trivial one-offs.
- If there are **no** substantive relationships, respond with a brief summary only.
- Prefer batch or group tools when relevant to minimize the number of tool calls.
- When you have extracted the most relevant insights, stop calling tools and respond with \
  a brief summary of what you found.\
"""

# Match email addresses in chain text (e.g. FROM/TO lines in CSV-style chains).
EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")

# Triage: skip chains that are unlikely to have significant relationships.
MIN_ADDRESSES_FOR_TRIAGE = 2
MIN_BODY_LENGTH = 150
SKIP_PATTERNS = re.compile(
    r"out of office|ooo|automatic reply|auto-reply|unsubscribe|no-reply@|do not reply|mailer-daemon",
    re.IGNORECASE,
)
MAX_AGENT_ROUNDS = 5

# summarize_edges: parallel LLM calls and batch Neo4j writes
MAX_SUMMARY_WORKERS = 8
SUMMARY_WRITE_BATCH_SIZE = 25


def should_process_chain(chain_text: str, people: Optional[list[str]] = None) -> bool:
    """
    Return False if the chain is clearly low-value (trivial, automated, or too small).
    Uses heuristics only; no LLM call.
    """
    if people is not None:
        addresses = people
    else:
        addresses = parse_emails_from_chain(chain_text)

    if len(addresses) < MIN_ADDRESSES_FOR_TRIAGE:
        return False
    if SKIP_PATTERNS.search(chain_text):
        return False
    # Rough body length: strip common header lines, count the rest
    body = re.sub(r"^(From:|To:|Cc:|Subject:)\s*.*$", "", chain_text, flags=re.MULTILINE)
    body = re.sub(r"---+\s*", "", body)
    if len(body.strip()) < MIN_BODY_LENGTH:
        return False
    return True


def parse_emails_from_chain(chain_text: str) -> list[str]:
    """Extract unique email addresses from CSV-style chain_text (FROM:/TO: lines)."""
    return list(dict.fromkeys(EMAIL_RE.findall(chain_text)))


def run_agent_from_chain_text(chain_text: str, people: Optional[list[str]] = None) -> str:
    """
    Run the agent on a single email chain string (e.g. chain_text from your CSV).
    Parses email addresses from the chain and calls run_agent.
    Skips chains that fail triage (should_process_chain).
    """
    if people is None:
        addresses = parse_emails_from_chain(chain_text)
    else:
        addresses = people
    if not addresses:
        return "(no email addresses found in chain)"
    if not should_process_chain(chain_text, addresses):
        return "(skipped: chain unlikely to have significant relationships)"
    return run_agent(addresses, chain_text)


def run_agent(email_addresses: list[str], email_chain: str) -> str:
    """
    Run the agentic loop on one email chain.

    Returns a text summary of what was ingested.
    """
    driver = get_driver()
    ensure_constraints(driver)

    with driver.session() as session:
        session.execute_write(upsert_persons, email_addresses)

    address_list = "\n".join(f"- {addr}" for addr in email_addresses)
    user_message = (
        f"People involved (use these names exactly):\n{address_list}\n\n"
        f"--- EMAIL CHAIN ---\n{email_chain}"
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_message},
    ]

    modified_pairs: set[tuple[str, str]] = set()
    round_count = 0

    while round_count < MAX_AGENT_ROUNDS:
        round_count += 1
        response = client.chat.completions.create(
            model=OPENROUTER_MODEL,
            messages=messages,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
        )

        choice = response.choices[0]
        assistant_msg = choice.message
        messages.append(assistant_msg)

        if not assistant_msg.tool_calls:
            break

        for tool_call in assistant_msg.tool_calls:
            args = json.loads(tool_call.function.arguments)
            name = tool_call.function.name
            comment = args["comment"]

            if name == "add_relationship_comments_batch":
                from_person = args["from_person"].strip()
                to_people = [p.strip() for p in (args.get("to_people") or [])]
                to_people = [p for p in to_people if p != from_person]
                with driver.session() as session:
                    session.execute_write(
                        append_comment_batch, from_person, to_people, comment
                    )
                for p in to_people:
                    modified_pairs.add(tuple(sorted([from_person, p])))
                tool_result = {"status": "ok", "person": from_person, "to_count": len(to_people)}
            
            elif name == "add_relationship_group":
                people = [p.strip() for p in (args.get("people") or [])]
                with driver.session() as session:
                    session.execute_write(
                        append_comment_recipient_pairs,
                        people,
                        comment,
                    )
                # Add all pairs to modified_pairs for count increment logic
                for p1, p2 in itertools.combinations(people, 2):
                    modified_pairs.add(tuple(sorted([p1, p2])))
                tool_result = {"status": "ok", "group_count": len(people)}
            
            else:
                from_person = args["from_person"].strip()
                to_person = args["to_person"].strip()
                with driver.session() as session:
                    session.execute_write(append_comment, from_person, to_person, comment)
                modified_pairs.add(tuple(sorted([from_person, to_person])))
                tool_result = {"status": "ok", "from": from_person, "to": to_person}

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(tool_result),
            })

    # Increment email_count once per modified pair for this email chain (one transaction)
    if modified_pairs:
        pairs_list = list(modified_pairs)
        with driver.session() as session:
            session.execute_write(increment_email_count_batch, pairs_list)

    driver.close()

    summary = assistant_msg.content or "(no summary returned)"
    print(f"Agent finished: {len(modified_pairs)} relationship(s) annotated.")
    return summary


def _summarize_one_edge(edge: dict) -> tuple[str, str, str] | None:
    """Call LLM for one edge; return (email_a, email_b, summary) or None on failure."""
    comments = edge.get("comments") or []
    if not comments:
        return None
    comment_text = "\n".join(f"- {c}" for c in comments)
    prompt = (
        f"Below are observations about the relationship between "
        f"{edge['email_a']} and {edge['email_b']}:\n\n"
        f"{comment_text}\n\n"
        f"Write a 1-2 sentence summary of their overall relationship."
    )
    try:
        response = client.chat.completions.create(
            model=OPENROUTER_MODEL,
            messages=[{"role": "user", "content": prompt}],
        )
        summary = (response.choices[0].message.content or "").strip()
        if not summary:
            return None
        return (edge["email_a"], edge["email_b"], summary)
    except Exception:
        return None


def summarize_edges(
    emails: Optional[list[str]] = None,
    skip_existing: bool = True,
    max_workers: int = MAX_SUMMARY_WORKERS,
) -> int:
    """
    Generate LLM summaries for edges that have comments.

    - If `emails` is provided, only summarize edges involving those addresses.
    - If `skip_existing` is True (default), edges that already have a summary are skipped.
    - `max_workers` limits concurrent LLM calls (default 8); lower if you hit rate limits.
    Returns the number of edges summarized.
    """
    driver = get_driver()

    with driver.session() as session:
        edges = session.execute_read(get_all_edges)

    if emails:
        email_set = set(emails)
        edges = [e for e in edges if e["email_a"] in email_set or e["email_b"] in email_set]

    if skip_existing:
        edges = [e for e in edges if not (e.get("summary") or "").strip()]
    to_process = [e for e in edges if e.get("comments")]

    if not to_process:
        driver.close()
        print("No edges to summarize.")
        return 0

    count = 0
    batch: list[tuple[str, str, str]] = []

    def flush_batch():
        nonlocal count
        if not batch:
            return
        with driver.session() as session:
            session.execute_write(set_summary_batch, batch)
        count += len(batch)
        for a, b, _ in batch:
            print(f"  Summarized {a} <-> {b}")
        batch.clear()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_summarize_one_edge, edge): edge for edge in to_process}
        for future in as_completed(futures):
            result = future.result()
            if result:
                batch.append(result)
                if len(batch) >= SUMMARY_WRITE_BATCH_SIZE:
                    flush_batch()

    flush_batch()
    driver.close()
    print(f"Summarized {count} edge(s).")
    return count