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

from openai import OpenAI
from config import OPENROUTER_API_KEY, OPENROUTER_MODEL
from graph import (
    get_driver,
    ensure_constraints,
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
                "from_email": {"type": "string", "description": "Email of one person."},
                "to_email": {"type": "string", "description": "Email of the other person."},
                "comment": {"type": "string", "description": "Concise observation about this pair."},
            },
            "required": ["from_email", "to_email", "comment"],
        },
    },
}

TOOL_ADD_BATCH = {
    "type": "function",
    "function": {
        "name": "add_relationship_comments_batch",
        "description": (
            "Record the same observation for one sender and many recipients in one call "
            "(e.g. one person emailed a group). Creates sender–recipient edges and also "
            "links recipients to each other as 'same audience' (copied together). Use when "
            "one person communicated the same thing to multiple people."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "from_email": {"type": "string", "description": "Sender / central person."},
                "to_emails": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of recipient email addresses.",
                },
                "comment": {"type": "string", "description": "Concise observation (same for all)."},
            },
            "required": ["from_email", "to_emails", "comment"],
        },
    },
}

TOOL_SCHEMAS = [TOOL_ADD_ONE, TOOL_ADD_BATCH]

SYSTEM_PROMPT = """\
You are a relationship-extraction agent. You will receive an email chain and \
a list of email addresses that appear in it.

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

Tools:
- `add_relationship_comment`: one (from_email, to_email, comment). Use for a single pair \
  or when each relationship has a different observation.
- `add_relationship_comments_batch`: (from_email, to_emails[], comment). Use when one \
  person sent the same kind of communication to many recipients (e.g. group email). \
  Records sender–recipient edges and also links recipients to each other (same audience).

Guidelines:
- Only use email addresses from the provided list.
- **Record only important, actionable relationship dynamics** (especially suspicious ones). \
  Do NOT add relationships for: routine FYI, out-of-office, single logistical reply, \
  trivial one-off mentions, or when there is no substantive or suspicious dynamic.
- If there are **no** such significant or suspicious relationships in the chain, do not call any tools. \
  Respond with a brief summary only (e.g. "No significant or suspicious relationship dynamics in this chain.").
- Extract at most 5–7 of the most important (and suspicious, when present) observations per chain; skip the rest.
- Prefer the batch tool when one sender emailed many people with the same observation.
- Be specific and ground observations in the email content; for suspicious behaviour, note what was said or implied.
- When you have extracted all relevant insights, stop calling tools and respond with \
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


def should_process_chain(chain_text: str) -> bool:
    """
    Return False if the chain is clearly low-value (trivial, automated, or too small).
    Uses heuristics only; no LLM call.
    """
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


def run_agent_from_chain_text(chain_text: str) -> str:
    """
    Run the agent on a single email chain string (e.g. chain_text from your CSV).
    Parses email addresses from the chain and calls run_agent.
    Skips chains that fail triage (should_process_chain).
    """
    addresses = parse_emails_from_chain(chain_text)
    if not addresses:
        return "(no email addresses found in chain)"
    if not should_process_chain(chain_text):
        return "(skipped: chain unlikely to have significant relationships)"
    return run_agent(addresses, chain_text)


def run_agent(email_addresses: list[str], email_chain: str) -> str:
    """
    Run the agentic loop on one email chain.

    Returns a text summary of what was ingested.
    """
    driver = get_driver()
    ensure_constraints(driver)

    address_list = "\n".join(f"- {addr}" for addr in email_addresses)
    user_message = (
        f"Email addresses involved:\n{address_list}\n\n"
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
            from_email = args["from_email"]
            comment = args["comment"]

            if name == "add_relationship_comments_batch":
                to_emails = args.get("to_emails") or []
                to_emails = [e for e in to_emails if e != from_email]
                recipient_comment = f"Same audience (copied together on email from {from_email}): {comment}"
                with driver.session() as session:
                    session.execute_write(
                        append_comment_batch, from_email, to_emails, comment
                    )
                    if len(to_emails) >= 2:
                        session.execute_write(
                            append_comment_recipient_pairs,
                            to_emails,
                            recipient_comment,
                        )
                for to_email in to_emails:
                    modified_pairs.add(tuple(sorted([from_email, to_email])))
                tool_result = {"status": "ok", "from": from_email, "to_count": len(to_emails)}
            else:
                to_email = args["to_email"]
                with driver.session() as session:
                    session.execute_write(append_comment, from_email, to_email, comment)
                modified_pairs.add(tuple(sorted([from_email, to_email])))
                tool_result = {"status": "ok", "from": from_email, "to": to_email}

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
